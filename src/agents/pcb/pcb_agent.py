"""
PCB Agent — generates PCB designs via "vibe coding."

Uses Claude to generate:
1. A schematic description (component connections)
2. KiCad schematic file
3. PCB layout recommendations

For a hackathon demo, we focus on generating a clear schematic +
wiring guide rather than pixel-perfect Gerbers.
"""
import json
from pathlib import Path

import anthropic

from src.agents.orchestrator import AgentMessage, parse_json_response, MODEL_GENERATION

OUTPUT_DIR = Path("output/pcb")


class PCBAgent:
    def __init__(self):
        self.client = anthropic.Anthropic()

    async def handle(self, msg: AgentMessage) -> dict:
        requirements = msg.payload.get("requirements", {})
        bom = msg.payload.get("bom", [])

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Step 1: Generate circuit design (connections + schematic description)
        print("      Generating circuit design...")
        circuit = await self._design_circuit(requirements, bom)

        # Step 2: Generate KiCad schematic
        print("      Generating KiCad schematic...")
        schematic = await self._generate_schematic(requirements, bom, circuit)
        schem_path = OUTPUT_DIR / "schematic.kicad_sch"
        schem_path.write_text(schematic)

        # Step 3: Board layout recommendations
        print("      Generating board layout...")
        layout = await self._generate_layout(requirements, bom, circuit)

        return {
            "circuit_design": circuit,
            "schematic_path": str(schem_path),
            "layout": layout,
            "dimensions": circuit.get("board_dimensions", {"width": 60, "height": 40}),
            "notes": "AI-generated — review before fabrication",
        }

    async def _design_circuit(self, requirements: dict, bom: list) -> dict:
        """Generate the circuit design: what connects to what."""
        response = self.client.messages.create(
            model=MODEL_GENERATION,
            max_tokens=4000,
            system="""You are an expert electronics engineer. Design a circuit for the given project.

Return ONLY JSON (no markdown):
{
    "board_dimensions": {"width": 60, "height": 40},
    "power_rails": [{"name": "3.3V", "source": "LDO from USB 5V"}, ...],
    "connections": [
        {"from": "ESP32 GPIO2", "to": "OV2640 SDA", "type": "I2C"},
        {"from": "ESP32 GPIO4", "to": "LED", "type": "digital", "notes": "via 220Ω resistor"},
        ...
    ],
    "decoupling": ["100nF on each IC VCC pin", "10µF on power input"],
    "notes": "design notes and considerations"
}

Be specific with pin assignments. Include power connections, decoupling, pull-up resistors for I2C, etc.""",
            messages=[{
                "role": "user",
                "content": f"Project: {json.dumps(requirements)}\nBOM: {json.dumps(bom)}",
            }],
        )
        return parse_json_response(response.content[0].text)

    async def _generate_schematic(self, requirements: dict, bom: list, circuit: dict) -> str:
        """Generate a KiCad schematic file (.kicad_sch)."""
        response = self.client.messages.create(
            model=MODEL_GENERATION,
            max_tokens=8000,
            system="""You are an expert KiCad PCB designer. Generate a valid KiCad 7+ schematic file (.kicad_sch format).

Rules:
- Use the KiCad 7 S-expression format
- Include all components from the BOM with proper symbols
- Wire power (VCC, GND) and signal connections per the circuit design
- Add decoupling capacitors
- Use proper reference designators (U1, R1, C1, etc.)
- Include a title block

Output ONLY the raw .kicad_sch file content — no explanation, no markdown fences.""",
            messages=[{
                "role": "user",
                "content": f"Project: {json.dumps(requirements)}\nBOM: {json.dumps(bom)}\nCircuit: {json.dumps(circuit)}",
            }],
        )
        return response.content[0].text

    async def _generate_layout(self, requirements: dict, bom: list, circuit: dict) -> dict:
        """Generate PCB layout recommendations."""
        size = requirements.get("size_constraint", "medium")
        response = self.client.messages.create(
            model=MODEL_GENERATION,
            max_tokens=3000,
            system=f"""You are a PCB layout expert. Generate layout recommendations for a {size} board.

Return ONLY JSON (no markdown):
{{
    "layers": 2,
    "board_shape": "rectangular",
    "dimensions_mm": {{"width": 60, "height": 40}},
    "component_placement": [
        {{"ref": "U1", "component": "ESP32", "position": "center", "notes": "keep antenna at board edge"}},
        ...
    ],
    "routing_notes": ["keep I2C traces short", "ground plane on bottom layer", ...],
    "mounting": ["4x M3 mounting holes in corners"],
    "manufacturing": {{
        "min_trace_width": "0.2mm",
        "min_clearance": "0.2mm",
        "recommended_fab": "JLCPCB or PCBWay",
        "estimated_cost_5pcs": 150
    }}
}}""",
            messages=[{
                "role": "user",
                "content": f"BOM: {json.dumps(bom)}\nCircuit: {json.dumps(circuit)}",
            }],
        )
        return parse_json_response(response.content[0].text)
