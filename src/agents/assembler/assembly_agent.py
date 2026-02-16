"""
Assembly Agent — generates step-by-step assembly instructions.

Produces a complete build guide including tools, safety warnings,
soldering steps, 3D printing settings, and testing procedures.
"""
import json

import anthropic

from src.agents.orchestrator import AgentMessage, parse_json_response, MODEL_GENERATION


class AssemblyAgent:
    def __init__(self):
        self.client = anthropic.Anthropic()

    async def handle(self, msg: AgentMessage) -> dict:
        requirements = msg.payload.get("requirements", {})
        bom = msg.payload.get("bom", [])
        pcb = msg.payload.get("pcb", {})
        cad = msg.payload.get("cad", {})

        response = self.client.messages.create(
            model=MODEL_GENERATION,
            max_tokens=5000,
            system="""You are a hardware assembly expert writing instructions for a DIY electronics project. The target reader may be a beginner.

Return ONLY JSON (no markdown):
{
    "difficulty": "beginner|intermediate|advanced",
    "estimated_time_hours": 2.5,
    "tools_required": [
        {"name": "soldering iron", "notes": "temperature-controlled, 350°C"},
        ...
    ],
    "materials_included": ["solder wire", "heat shrink tubing", ...],
    "safety_warnings": [
        "Wear safety glasses when soldering",
        ...
    ],
    "steps": [
        {
            "step": 1,
            "title": "3D Print the Enclosure",
            "description": "Print enclosure.stl and lid.stl using PLA filament...",
            "substeps": ["Load PLA filament", "Set layer height to 0.2mm", ...],
            "tips": ["Use a brim for better bed adhesion"],
            "image_hint": "photo of 3D printer with enclosure"
        },
        ...
    ],
    "testing": [
        {
            "test": "Power-on test",
            "procedure": "Connect USB cable and verify power LED lights up",
            "expected_result": "Blue LED on ESP32 blinks"
        },
        ...
    ],
    "troubleshooting": [
        {"problem": "No power LED", "solutions": ["Check USB cable", "Verify solder joints on power pins"]},
        ...
    ]
}

Be thorough. Include EVERY step from opening the package to final testing.""",
            messages=[{
                "role": "user",
                "content": f"Project: {json.dumps(requirements)}\nBOM: {json.dumps(bom)}\nPCB: {json.dumps(pcb)}\nCAD: {json.dumps(cad)}",
            }],
        )
        return parse_json_response(response.content[0].text)
