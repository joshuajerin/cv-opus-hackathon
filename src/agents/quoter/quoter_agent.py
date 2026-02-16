"""
Quoter Agent — deterministic cost breakdown in USD.

Computes costs from BOM (sourced in INR from robu.in),
converts to USD, adds PCB fab, 3D printing, shipping estimates.
No LLM needed — pure arithmetic.
"""
from src.agents.orchestrator import AgentMessage

# Conversion
INR_TO_USD = 0.012  # ~₹83.3 per $1

class QuoterAgent:
    """Calculates project cost — no LLM, just math."""

    # Base costs (INR, converted at output)
    PCB_BASE_INR = 150           # JLCPCB 5-pack, small board
    PCB_PER_SQCM_INR = 2.0      # per sq cm over 25 sq cm
    PRINT_PER_GRAM_INR = 5.0    # PLA cost/gram
    PRINT_BASE_GRAMS = 40       # estimated enclosure weight
    SHIPPING_INR = 80            # domestic flat rate
    ASSEMBLY_FEE_INR = 0         # DIY
    PLATFORM_FEE_PCT = 0.10     # 10%

    async def handle(self, msg: AgentMessage) -> dict:
        bom = msg.payload.get("bom", [])
        cad = msg.payload.get("cad", {})
        pcb = msg.payload.get("pcb_design", msg.payload.get("pcb", {}))

        # ── Parts cost (INR from DB) ──
        parts_inr = 0.0
        items = []
        for part in bom:
            price = part.get("price", part.get("estimated_price", 0)) or 0
            qty = part.get("quantity", 1)
            line = price * qty
            parts_inr += line
            items.append({
                "name": part.get("name", "Unknown"),
                "unit_price_inr": round(price, 2),
                "unit_price_usd": round(price * INR_TO_USD, 2),
                "quantity": qty,
                "total_usd": round(line * INR_TO_USD, 2),
            })

        # ── PCB fabrication ──
        dims = pcb.get("layout", pcb.get("dimensions", {}))
        board_w = dims.get("width", dims.get("dimensions_mm", {}).get("width", 60))
        board_h = dims.get("height", dims.get("dimensions_mm", {}).get("height", 40))
        if isinstance(board_w, dict): board_w = board_w.get("width", 60)
        if isinstance(board_h, dict): board_h = board_h.get("height", 40)
        board_area = board_w * board_h / 100  # sq cm
        pcb_inr = self.PCB_BASE_INR
        if board_area > 25:
            pcb_inr += (board_area - 25) * self.PCB_PER_SQCM_INR

        # ── 3D printing ──
        ps = cad.get("print_settings", {})
        grams = ps.get("estimated_weight_grams", self.PRINT_BASE_GRAMS)
        print_inr = grams * self.PRINT_PER_GRAM_INR

        # ── Assembly / Shipping ──
        asm_inr = self.ASSEMBLY_FEE_INR
        ship_inr = self.SHIPPING_INR

        # ── Convert everything to USD ──
        parts_usd = parts_inr * INR_TO_USD
        pcb_usd = pcb_inr * INR_TO_USD
        print_usd = print_inr * INR_TO_USD
        asm_usd = asm_inr * INR_TO_USD
        ship_usd = ship_inr * INR_TO_USD
        subtotal = parts_usd + pcb_usd + print_usd + asm_usd + ship_usd
        platform = subtotal * self.PLATFORM_FEE_PCT
        total = subtotal + platform

        return {
            "breakdown": {
                "parts": {"total": round(parts_usd, 2), "items": items},
                "pcb_fabrication": {
                    "total": round(pcb_usd, 2),
                    "board_size_mm": f"{board_w}x{board_h}",
                    "quantity": 5,
                    "vendor": "JLCPCB / PCBWay",
                },
                "3d_printing": {
                    "total": round(print_usd, 2),
                    "weight_grams": grams,
                    "material": ps.get("material", "PLA"),
                },
                "assembly": {"total": round(asm_usd, 2), "type": "DIY"},
                "shipping": {"total": round(ship_usd, 2), "method": "Standard"},
                "platform_fee": {
                    "total": round(platform, 2),
                    "rate": f"{self.PLATFORM_FEE_PCT * 100:.0f}%",
                },
            },
            "subtotal": round(subtotal, 2),
            "total": round(total, 2),
            "currency": "USD",
            "conversion_rate": f"1 USD = {1/INR_TO_USD:.1f} INR",
            "delivery": "5-7 days (parts) + 3-5 days (PCB fab)",
            "notes": [
                "Parts sourced from robu.in (INR converted at $1 = ₹83.3)",
                "PCB via JLCPCB (5-pack minimum)",
                "3D printing via local service bureau",
                "Assembly: DIY with included instructions",
            ],
        }
