"""
Parts Agent — searches the robu.in database and builds a BOM.

Given requirements from the orchestrator, it:
1. Searches the parts DB using FTS and direct queries
2. Uses Claude to rank/select the best parts for the project
3. Returns a Bill of Materials with prices and robu.in URLs
"""
import json
import sqlite3
from pathlib import Path

import anthropic

from src.db.schema import init_db, DB_PATH
from src.agents.orchestrator import AgentMessage, parse_json_response, MODEL_REASONING, MODEL_GENERATION


class PartsAgent:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.conn = init_db(db_path)
        self.conn.row_factory = sqlite3.Row
        self.client = anthropic.Anthropic()

    def _search_parts(self, query: str, limit: int = 15) -> list[dict]:
        """Search parts via FTS, falling back to LIKE if FTS fails."""
        results = []

        # Try FTS first
        try:
            rows = self.conn.execute(
                """SELECT p.id, p.name, p.url, p.sku, p.price, p.currency,
                          p.in_stock, p.description, p.image_url, c.name as category
                   FROM parts_fts f
                   JOIN parts p ON f.rowid = p.id
                   LEFT JOIN categories c ON p.category_id = c.id
                   WHERE parts_fts MATCH ?
                   ORDER BY p.price > 0 DESC, p.price ASC
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            results = [dict(r) for r in rows]
        except Exception:
            pass

        # Fallback: LIKE search
        if not results:
            like_q = f"%{query}%"
            rows = self.conn.execute(
                """SELECT p.id, p.name, p.url, p.sku, p.price, p.currency,
                          p.in_stock, p.description, p.image_url, c.name as category
                   FROM parts p
                   LEFT JOIN categories c ON p.category_id = c.id
                   WHERE p.name LIKE ?
                   ORDER BY p.price > 0 DESC, p.price ASC
                   LIMIT ?""",
                (like_q, limit),
            ).fetchall()
            results = [dict(r) for r in rows]

        return results

    def _get_db_stats(self) -> dict:
        """Get DB stats for context."""
        total = self.conn.execute("SELECT COUNT(*) FROM parts").fetchone()[0]
        priced = self.conn.execute("SELECT COUNT(*) FROM parts WHERE price > 0").fetchone()[0]
        cats = self.conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        return {"total_parts": total, "priced_parts": priced, "categories": cats}

    async def handle(self, msg: AgentMessage) -> list[dict]:
        requirements = msg.payload
        components_needed = requirements.get("components_needed", [])
        db_stats = self._get_db_stats()

        # Search for each component type
        all_candidates = {}
        for component in components_needed:
            # Try multiple search strategies
            search_terms = [component]
            # Also try individual words for multi-word queries
            words = component.split()
            if len(words) > 1:
                search_terms.extend(words)

            for term in search_terms:
                results = self._search_parts(term, limit=10)
                for r in results:
                    key = r["url"] or r["name"]
                    if key not in all_candidates:
                        r["search_term"] = component
                        all_candidates[key] = r

        candidates_list = list(all_candidates.values())
        print(f"   Found {len(candidates_list)} candidate parts from DB")

        # Build the prompt for Claude
        if candidates_list:
            return await self._select_from_candidates(requirements, candidates_list, db_stats)
        else:
            print(f"   No DB matches — using Claude's knowledge of robu.in inventory")
            return await self._suggest_parts_without_db(requirements)

    async def _select_from_candidates(
        self, requirements: dict, candidates: list[dict], db_stats: dict
    ) -> list[dict]:
        """Use Claude to select the best parts from DB candidates."""
        # Trim candidates to avoid token limits
        slim_candidates = []
        for c in candidates[:60]:
            slim_candidates.append({
                "name": c["name"],
                "url": c.get("url", ""),
                "price": c.get("price", 0),
                "in_stock": c.get("in_stock", 1),
                "category": c.get("category", ""),
                "search_term": c.get("search_term", ""),
            })

        response = self.client.messages.create(
            model=MODEL_REASONING,
            max_tokens=4000,
            system=f"""You are a hardware parts selector for robu.in (Indian electronics store).
Database has {db_stats['total_parts']} parts ({db_stats['priced_parts']} with prices).

Given project requirements and candidate parts found in the database, select the BEST parts to build this project. You may also suggest parts that aren't in the candidates if they're commonly available on robu.in.

Return ONLY a JSON array (no markdown):
[
  {{
    "name": "exact product name",
    "url": "robu.in product URL if available",
    "price": 123.00,
    "quantity": 1,
    "category": "component type",
    "reason": "why this part"
  }}
]

Rules:
- Include ALL parts needed (microcontroller, sensors, passive components, connectors, wires, power)
- Prefer in-stock items with prices
- If a needed part isn't in the candidates, add it with estimated_price and note "not in DB"
- Use realistic INR prices
- Don't forget basics: resistors, capacitors, headers, jumper wires, breadboard/perfboard, USB cable""",
            messages=[{
                "role": "user",
                "content": f"Project requirements:\n{json.dumps(requirements, indent=2)}\n\nCandidate parts from database:\n{json.dumps(slim_candidates, indent=2)}",
            }],
        )
        return parse_json_response(response.content[0].text)

    async def _suggest_parts_without_db(self, requirements: dict) -> list[dict]:
        """When DB has no matches, use Claude to suggest a full BOM."""
        response = self.client.messages.create(
            model=MODEL_REASONING,
            max_tokens=4000,
            system="""You are a hardware parts expert familiar with robu.in's inventory (Indian electronics/robotics store).

Given project requirements, suggest a complete, realistic Bill of Materials.

Return ONLY a JSON array (no markdown):
[
  {
    "name": "product name as it would appear on robu.in",
    "estimated_price": 123.00,
    "quantity": 1,
    "category": "component type",
    "reason": "why needed"
  }
]

Use realistic INR prices. Include everything: MCU, sensors, passive components, connectors, power supply, wires, enclosure hardware (screws, standoffs), etc.""",
            messages=[{
                "role": "user",
                "content": f"Requirements:\n{json.dumps(requirements, indent=2)}",
            }],
        )
        return parse_json_response(response.content[0].text)
