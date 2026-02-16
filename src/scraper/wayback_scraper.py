"""
Scrape robu.in product catalog via the Wayback Machine.

Robu.in has aggressive Cloudflare protection, but Wayback Machine
has cached snapshots we can use to build our parts database.

Strategy:
1. Grab homepage snapshot → extract all 500+ category URLs
2. For each category, fetch Wayback snapshot → extract products
3. Follow pagination within categories
4. Store everything in SQLite with FTS
"""
import re
import json
import time
import sqlite3
import sys
from pathlib import Path
from html import unescape
from urllib.parse import urljoin

import httpx

from src.db.schema import init_db, DB_PATH

WAYBACK_PREFIX = "https://web.archive.org/web/2025/"
BASE_URL = "https://robu.in"
RATE_LIMIT_SECONDS = 1.5  # be nice to Wayback


def fetch_wayback(url: str, client: httpx.Client, retries: int = 3) -> str | None:
    """Fetch a page via Wayback Machine with retries."""
    wb_url = WAYBACK_PREFIX + url
    for attempt in range(retries):
        try:
            resp = client.get(wb_url, timeout=30, follow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 5000:
                return resp.text
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
        except Exception as e:
            print(f"    Fetch error (attempt {attempt+1}): {e}")
            time.sleep(3)
    return None


def extract_categories(html: str) -> list[dict]:
    """Extract category URLs and names from robu.in homepage."""
    # Find all product-category links
    pattern = r'href="(?:https?://web\.archive\.org/web/\d+/)?(?:https?://)?robu\.in/(product-category/[^"#?]+)"'
    raw_cats = set(re.findall(pattern, html))

    categories = []
    seen = set()
    for cat_path in sorted(raw_cats):
        # Normalize
        cat_path = cat_path.rstrip("/")
        if cat_path in seen:
            continue
        seen.add(cat_path)

        # Derive name from URL
        parts = cat_path.replace("product-category/", "").split("/")
        name = parts[-1].replace("-", " ").title()
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else None

        categories.append({
            "path": cat_path,
            "name": name,
            "url": f"{BASE_URL}/{cat_path}/",
            "parent_path": parent_path,
        })

    return categories


def extract_products(html: str) -> list[dict]:
    """Extract product info from a category page HTML."""
    products = []

    # WooCommerce uses <ul class="products ..."> for the product grid.
    # We target that container first to avoid matching nav items.
    products_sections = re.findall(
        r'<ul[^>]*class="[^"]*products[^"]*columns[^"]*"[^>]*>(.*?)</ul>',
        html, re.DOTALL | re.IGNORECASE,
    )
    # Fallback: broader products class
    if not products_sections:
        products_sections = re.findall(
            r'<ul[^>]*class="[^"]*products[^"]*"[^>]*>(.*?)</ul>',
            html, re.DOTALL | re.IGNORECASE,
        )

    section_html = "\n".join(products_sections) if products_sections else html

    # Extract product blocks inside the grid
    blocks = re.findall(
        r'<li[^>]*class="[^"]*product[^"]*"[^>]*>(.*?)</li>',
        section_html, re.DOTALL | re.IGNORECASE,
    )

    for block in blocks:
        product = {}

        # Must have an h2 (product title) — nav items don't
        name_match = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
        if not name_match:
            continue
        product["name"] = unescape(re.sub(r'<[^>]+>', '', name_match.group(1))).strip()

        # Product URL — must point to /product/ (not /product-category/)
        link_match = re.search(
            r'href="(?:https?://web\.archive\.org/web/\d+/)?(https?://robu\.in/product/[^"]+)"',
            block,
        )
        if not link_match:
            continue
        product["url"] = re.sub(
            r'https?://web\.archive\.org/web/\d+[a-z]*/', '', link_match.group(1)
        )

        # Price — WooCommerce uses:
        #   <bdi><span class="...currencySymbol">&#8377;</span>&nbsp;28.00</bdi>
        # For sale items: <ins><span ...><bdi>...</bdi></span></ins>
        # Strategy: grab all text inside <bdi> tags, extract the number after currency symbol

        # Prefer <ins> (sale price) over regular price
        ins_match = re.search(r'<ins>.*?<bdi>(.*?)</bdi>', block, re.DOTALL)
        if ins_match:
            bdi_content = ins_match.group(1)
        else:
            bdi_match = re.search(r'<bdi>(.*?)</bdi>', block, re.DOTALL)
            bdi_content = bdi_match.group(1) if bdi_match else ""

        # Strip HTML tags and entities, then find the number
        bdi_text = re.sub(r'<[^>]+>', '', bdi_content)
        bdi_text = unescape(bdi_text).replace('\xa0', ' ').replace('&nbsp;', ' ')
        price_match = re.search(r'(\d[\d,]*\.?\d*)', bdi_text)
        price_text = price_match.group(1).replace(",", "") if price_match else "0"
        product["price"] = float(price_text) if price_text else 0.0

        # Image — prefer data-lazy-src (actual image), skip SVG placeholders
        img_match = re.search(r'data-lazy-src="([^"]+)"', block)
        if not img_match:
            img_match = re.search(r'<img[^>]*src="([^"]+)"', block)
        if img_match:
            img_url = img_match.group(1)
            if "svg" not in img_url:
                img_url = re.sub(r'https?://web\.archive\.org/web/\d+[a-z]*/', '', img_url)
                product["image_url"] = img_url

        # Stock status
        if "out-of-stock" in block.lower() or "out of stock" in block.lower():
            product["in_stock"] = 0
        else:
            product["in_stock"] = 1

        if product.get("name") and product.get("url"):
            products.append(product)

    return products


def get_pagination_count(html: str) -> int:
    """Get the total number of pages for a category."""
    page_nums = re.findall(r'<a[^>]*class="page-numbers"[^>]*>(\d+)</a>', html)
    if page_nums:
        return max(int(n) for n in page_nums)
    return 1


def store_category(conn: sqlite3.Connection, cat: dict) -> int:
    """Insert or get a category, return its ID."""
    conn.execute(
        "INSERT OR IGNORE INTO categories (name, url) VALUES (?, ?)",
        (cat["name"], cat["url"])
    )
    conn.commit()
    row = conn.execute("SELECT id FROM categories WHERE url = ?", (cat["url"],)).fetchone()
    return row[0]


def store_product(conn: sqlite3.Connection, product: dict, category_id: int):
    """Insert a product into the database."""
    if not product.get("url"):
        return
    conn.execute(
        """INSERT OR IGNORE INTO parts
           (name, url, price, image_url, category_id, in_stock)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            product["name"],
            product["url"],
            product.get("price", 0),
            product.get("image_url"),
            category_id,
            product.get("in_stock", 1),
        )
    )


def rebuild_fts(conn: sqlite3.Connection):
    """Rebuild the FTS index from the parts table."""
    try:
        conn.execute("DROP TABLE IF EXISTS parts_fts")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS parts_fts
            USING fts5(name, description, specs, content=parts, content_rowid=id)
        """)
        conn.execute("""
            INSERT INTO parts_fts(rowid, name, description, specs)
            SELECT id, name, COALESCE(description, ''), COALESCE(specs, '')
            FROM parts
        """)
        conn.commit()
    except Exception as e:
        print(f"  ⚠ FTS rebuild error: {e} — search may be limited")


def scrape_all(
    max_categories: int | None = None,
    db_path: str | Path = DB_PATH,
    verbose: bool = True,
    resume: bool = True,
):
    """Main scraping function — pulls everything via Wayback Machine."""
    conn = init_db(db_path)
    client = httpx.Client(
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; HardwareBuilder/0.1; research project)",
        },
        timeout=30,
    )

    # Step 1: Get all categories from homepage
    print("🌐 Fetching robu.in homepage via Wayback Machine...")
    homepage = fetch_wayback(BASE_URL, client)
    if not homepage:
        print("❌ Could not fetch homepage")
        return

    categories = extract_categories(homepage)
    print(f"📂 Found {len(categories)} categories")

    if max_categories:
        categories = categories[:max_categories]
        print(f"   (limiting to {max_categories})")

    # Resume support: skip already-scraped categories
    if resume:
        existing = set(
            row[0] for row in conn.execute("SELECT url FROM categories").fetchall()
        )
        before = len(categories)
        categories = [c for c in categories if c["url"] not in existing]
        if before != len(categories):
            print(f"   ⏩ Resuming: skipping {before - len(categories)} already-scraped categories")

    total_products = 0

    # Step 2: Scrape each category
    for i, cat in enumerate(categories):
        cat_id = store_category(conn, cat)
        cat_url = cat["url"]

        if verbose:
            print(f"\n[{i+1}/{len(categories)}] 📦 {cat['name']} → {cat_url}")

        html = fetch_wayback(cat_url, client)
        if not html:
            print("   ⚠ Could not fetch, skipping")
            time.sleep(RATE_LIMIT_SECONDS)
            continue

        # Extract products from page 1
        products = extract_products(html)
        total_pages = get_pagination_count(html)

        if verbose:
            print(f"   Page 1: {len(products)} products (total pages: {total_pages})")

        # Paginate
        for pg in range(2, min(total_pages + 1, 20)):  # cap at 20 pages per category
            pg_url = f"{cat_url}page/{pg}/"
            pg_html = fetch_wayback(pg_url, client)
            if pg_html:
                pg_products = extract_products(pg_html)
                if verbose:
                    print(f"   Page {pg}: {len(pg_products)} products")
                products.extend(pg_products)
            time.sleep(RATE_LIMIT_SECONDS)

        # Store all products
        for product in products:
            store_product(conn, product, cat_id)
        conn.commit()
        total_products += len(products)

        if verbose:
            print(f"   ✅ Saved {len(products)} products")

        time.sleep(RATE_LIMIT_SECONDS)

    # Rebuild FTS index
    print("\n🔍 Rebuilding full-text search index...")
    rebuild_fts(conn)

    total_in_db = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    total_cats = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    print(f"\n🎉 Done!")
    print(f"   Categories: {total_cats}")
    print(f"   Products scraped this run: {total_products}")
    print(f"   Total unique products in DB: {total_in_db}")

    conn.close()
    client.close()


if __name__ == "__main__":
    max_cats = int(sys.argv[1]) if len(sys.argv) > 1 else None
    scrape_all(max_categories=max_cats)
