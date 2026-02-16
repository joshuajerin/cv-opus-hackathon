"""
Robu.in scraper using Playwright to bypass Cloudflare.

Strategy:
1. Launch browser with stealth settings
2. Navigate through categories
3. Extract product details per category page
4. Store in SQLite via db.schema
"""
import asyncio
import json
import re
import sqlite3
from pathlib import Path

from playwright.async_api import async_playwright, Page, Browser

from src.db.schema import init_db, DB_PATH

BASE_URL = "https://robu.in"

# Known top-level category URLs from robu.in navigation
SEED_CATEGORIES = [
    "/product-category/sensors/",
    "/product-category/motors-drivers/",
    "/product-category/development-board/",
    "/product-category/3d-printer-accessories/",
    "/product-category/raspberry-pi/",
    "/product-category/arduino/",
    "/product-category/displays/",
    "/product-category/power-supply/",
    "/product-category/battery/",
    "/product-category/wireless-module/",
    "/product-category/camera-module/",
    "/product-category/cables-connectors/",
    "/product-category/led/",
    "/product-category/tools/",
    "/product-category/iot/",
    "/product-category/electronic-components/",
    "/product-category/mechanical-parts/",
    "/product-category/drones/",
    "/product-category/robotics/",
    "/product-category/pcb/",
]


async def wait_for_cloudflare(page: Page, timeout: int = 30000):
    """Wait for Cloudflare challenge to clear."""
    try:
        await page.wait_for_selector(
            "body:not(:has-text('Just a moment'))",
            timeout=timeout
        )
    except Exception:
        # Fallback: just wait and hope
        await asyncio.sleep(5)


async def scrape_category_page(page: Page, url: str) -> list[dict]:
    """Scrape all products from a single category page."""
    products = []
    await page.goto(url, wait_until="domcontentloaded")
    await wait_for_cloudflare(page)
    await asyncio.sleep(2)

    # Try to get product cards
    cards = await page.query_selector_all(".product-inner, .products li.product")
    for card in cards:
        try:
            name_el = await card.query_selector(".woocommerce-loop-product__title, .product-title, h2")
            name = await name_el.inner_text() if name_el else None

            link_el = await card.query_selector("a.woocommerce-LoopProduct-link, a[href*='/product/']")
            link = await link_el.get_attribute("href") if link_el else None

            price_el = await card.query_selector(".price .amount, .woocommerce-Price-amount")
            price_text = await price_el.inner_text() if price_el else "0"
            price = float(re.sub(r"[^\d.]", "", price_text or "0") or "0")

            img_el = await card.query_selector("img")
            img_url = await img_el.get_attribute("src") if img_el else None

            if name and link:
                products.append({
                    "name": name.strip(),
                    "url": link,
                    "price": price,
                    "image_url": img_url,
                })
        except Exception as e:
            print(f"  ⚠ Error parsing card: {e}")
            continue

    return products


async def scrape_product_detail(page: Page, url: str) -> dict:
    """Scrape detailed info from a single product page."""
    await page.goto(url, wait_until="domcontentloaded")
    await wait_for_cloudflare(page)
    await asyncio.sleep(1)

    detail = {}
    try:
        sku_el = await page.query_selector(".sku")
        detail["sku"] = await sku_el.inner_text() if sku_el else None

        desc_el = await page.query_selector(".woocommerce-product-details__short-description, #tab-description")
        detail["description"] = await desc_el.inner_text() if desc_el else None

        # Try to get specs from additional info table
        specs = {}
        rows = await page.query_selector_all(".woocommerce-product-attributes tr, .shop_attributes tr")
        for row in rows:
            label_el = await row.query_selector("th")
            value_el = await row.query_selector("td")
            if label_el and value_el:
                label = (await label_el.inner_text()).strip()
                value = (await value_el.inner_text()).strip()
                specs[label] = value
        detail["specs"] = json.dumps(specs) if specs else None

        stock_el = await page.query_selector(".stock")
        if stock_el:
            stock_text = await stock_el.inner_text()
            detail["in_stock"] = 0 if "out of stock" in stock_text.lower() else 1
        else:
            detail["in_stock"] = 1

    except Exception as e:
        print(f"  ⚠ Error scraping detail {url}: {e}")

    return detail


async def get_pagination_urls(page: Page) -> list[str]:
    """Get all pagination page URLs from current category."""
    urls = []
    links = await page.query_selector_all(".woocommerce-pagination a.page-numbers, .pagination a")
    for link in links:
        href = await link.get_attribute("href")
        text = await link.inner_text()
        if href and text.isdigit():
            urls.append(href)
    return list(set(urls))


async def scrape_all(detail: bool = False, max_categories: int | None = None):
    """Main scraping entrypoint."""
    conn = init_db()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # First, visit homepage to get past initial Cloudflare
        print("🌐 Visiting homepage to clear Cloudflare...")
        await page.goto(BASE_URL, wait_until="domcontentloaded")
        await wait_for_cloudflare(page, timeout=45000)
        await asyncio.sleep(3)

        categories = SEED_CATEGORIES[:max_categories] if max_categories else SEED_CATEGORIES

        for i, cat_path in enumerate(categories):
            cat_url = BASE_URL + cat_path
            cat_name = cat_path.strip("/").split("/")[-1].replace("-", " ").title()
            print(f"\n📦 [{i+1}/{len(categories)}] Scraping: {cat_name}")

            # Insert category
            conn.execute(
                "INSERT OR IGNORE INTO categories (name, url) VALUES (?, ?)",
                (cat_name, cat_url)
            )
            conn.commit()
            cat_id = conn.execute(
                "SELECT id FROM categories WHERE url = ?", (cat_url,)
            ).fetchone()[0]

            # Scrape first page
            products = await scrape_category_page(page, cat_url)
            print(f"  Found {len(products)} products on page 1")

            # Check pagination
            extra_pages = await get_pagination_urls(page)
            for pg_url in sorted(set(extra_pages)):
                pg_products = await scrape_category_page(page, pg_url)
                print(f"  Found {len(pg_products)} more products")
                products.extend(pg_products)

            # Store products
            for prod in products:
                if detail:
                    det = await scrape_product_detail(page, prod["url"])
                    prod.update(det)

                conn.execute(
                    """INSERT OR IGNORE INTO parts
                       (name, url, price, image_url, category_id, sku, description, specs, in_stock)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        prod["name"], prod["url"], prod["price"],
                        prod.get("image_url"), cat_id,
                        prod.get("sku"), prod.get("description"),
                        prod.get("specs"), prod.get("in_stock", 1),
                    )
                )
            conn.commit()
            print(f"  ✅ Saved {len(products)} products for {cat_name}")

        await browser.close()

    total = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    print(f"\n🎉 Done! Total parts in DB: {total}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(scrape_all(detail=False))
