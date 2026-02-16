"""
CLI runner for the hardware builder pipeline.

Usage:
    python run.py "I want to build a camera for an 8 year old"
    python run.py --search "ESP32"
    python run.py --stats
"""
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from src.agents.orchestrator import Orchestrator
from src.agents.parts_agent import PartsAgent
from src.agents.pcb.pcb_agent import PCBAgent
from src.agents.cad.cad_agent import CADAgent
from src.agents.assembler.assembly_agent import AssemblyAgent
from src.agents.quoter.quoter_agent import QuoterAgent
from src.db.schema import init_db, DB_PATH


def print_search(query: str):
    """Quick search the parts DB."""
    import sqlite3
    conn = init_db()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """SELECT p.name, p.price, p.url, c.name as category
               FROM parts_fts f JOIN parts p ON f.rowid = p.id
               LEFT JOIN categories c ON p.category_id = c.id
               WHERE parts_fts MATCH ? LIMIT 20""",
            (query,),
        ).fetchall()
    except Exception:
        rows = conn.execute(
            """SELECT p.name, p.price, p.url, c.name as category
               FROM parts p LEFT JOIN categories c ON p.category_id = c.id
               WHERE p.name LIKE ? LIMIT 20""",
            (f"%{query}%",),
        ).fetchall()
    
    print(f"🔍 Search: '{query}' → {len(rows)} results\n")
    for r in rows:
        price = f"₹{r['price']:,.0f}" if r['price'] else "no price"
        print(f"  {price:>10}  {r['name'][:60]}")
        if r['url']:
            print(f"             {r['url'][:70]}")
    conn.close()


def print_stats():
    """Print DB stats."""
    conn = init_db()
    total = conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
    priced = conn.execute("SELECT COUNT(*) FROM parts WHERE price > 0").fetchone()[0]
    cats = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    print(f"📊 Database: {total} parts ({priced} priced) across {cats} categories")
    
    if priced:
        stats = conn.execute("SELECT MIN(price), AVG(price), MAX(price) FROM parts WHERE price > 0").fetchone()
        print(f"   Prices: ₹{stats[0]:,.0f} – ₹{stats[2]:,.0f} (avg ₹{stats[1]:,.0f})")
    conn.close()


async def run_build(prompt: str):
    """Run the full build pipeline."""
    print(f"🚀 Hardware Builder")
    print(f"📝 Prompt: {prompt}")
    print(f"{'─' * 60}\n")

    orch = Orchestrator()
    orch.register_agent("parts", PartsAgent())
    orch.register_agent("pcb", PCBAgent())
    orch.register_agent("cad", CADAgent())
    orch.register_agent("assembler", AssemblyAgent())
    orch.register_agent("quoter", QuoterAgent())

    spec = await orch.run(prompt)

    # Save full output
    output_path = Path("output/project.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(spec), indent=2, default=str))

    print(f"\n{'═' * 60}")
    print(f"📦 PROJECT: {spec.requirements.get('project_name', 'Unknown')}")
    print(f"{'═' * 60}")
    
    if spec.bom:
        print(f"\n🔩 Bill of Materials ({len(spec.bom)} items):")
        for p in spec.bom:
            price = p.get("price", p.get("estimated_price", 0))
            qty = p.get("quantity", 1)
            print(f"   {qty}x {p['name'][:50]:50s} ₹{price * qty:>8,.0f}")
    
    if spec.quote:
        print(f"\n💰 Quote:")
        bd = spec.quote.get("breakdown", {})
        for key, val in bd.items():
            if isinstance(val, dict) and "total" in val:
                print(f"   {key:20s} ₹{val['total']:>10,.2f}")
        print(f"   {'─' * 33}")
        print(f"   {'TOTAL':20s} ₹{spec.total_cost:>10,.2f}")
        print(f"\n   📦 Delivery: {spec.delivery_estimate}")

    if spec.cad_files:
        print(f"\n📐 CAD Files: {', '.join(spec.cad_files)}")
    
    if spec.assembly.get("steps"):
        print(f"\n🔧 Assembly: {len(spec.assembly['steps'])} steps")
        print(f"   Difficulty: {spec.assembly.get('difficulty', '?')}")
        print(f"   Est. time: {spec.assembly.get('estimated_time_hours', '?')} hours")

    print(f"\n📄 Full output saved to: {output_path}")
    print(f"   Status: {spec.status}")
    if spec.errors:
        print(f"   ⚠ Errors: {'; '.join(spec.errors)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args:
        print("Usage:")
        print("  python run.py 'I want to build a camera for an 8 year old'")
        print("  python run.py --search 'ESP32'")
        print("  python run.py --stats")
        sys.exit(0)

    if args[0] == "--search":
        print_search(" ".join(args[1:]))
    elif args[0] == "--stats":
        print_stats()
    else:
        asyncio.run(run_build(" ".join(args)))
