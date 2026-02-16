"""
Orchestrator Agent — the brain.

Takes a user prompt like "I want to build a camera for an 8 year old"
and coordinates the pipeline:

1. Requirements analysis → structured project spec
2. Parts Agent → searches DB, selects components, builds BOM
3. PCB Agent → designs PCB layout (KiCad / vibe-coded)
4. CAD Agent → generates 3D-printable enclosure STL
5. Assembly Agent → creates assembly instructions
6. Quoter Agent → calculates total cost + delivery estimate
"""
import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable

import anthropic

import src.config  # noqa: F401 — auto-loads API key

MODEL_REASONING = "claude-opus-4-20250514"    # For complex reasoning (requirements, parts)
MODEL_GENERATION = "claude-opus-4-20250514"  # For generation tasks (PCB, CAD, assembly)


@dataclass
class AgentMessage:
    """Inter-agent message."""
    from_agent: str
    to_agent: str
    task: str
    payload: dict = field(default_factory=dict)
    status: str = "pending"  # pending | in_progress | done | error
    result: Any = None
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ProjectSpec:
    """Full project specification built incrementally by agents."""
    prompt: str
    requirements: dict = field(default_factory=dict)
    bom: list[dict] = field(default_factory=list)
    pcb_design: dict | None = None
    cad_files: list[str] = field(default_factory=list)
    assembly: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)
    total_cost: float = 0.0
    currency: str = "INR"
    delivery_estimate: str = ""
    status: str = "planning"
    errors: list[str] = field(default_factory=list)


def parse_json_response(text: str) -> Any:
    """Extract JSON from a Claude response, handling markdown fences."""
    # Try direct parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from ```json ... ``` blocks
    match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding first { or [ and matching to last } or ]
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse JSON from response: {text[:200]}...")


class Orchestrator:
    """Main orchestrator that routes tasks between agents."""

    def __init__(self, db_path: str = "parts.db"):
        self.client = anthropic.Anthropic()
        self.db_path = db_path
        self.agents: dict[str, Any] = {}
        self.message_log: list[AgentMessage] = []
        self.on_status: Callable[[str], None] | None = None  # callback for status updates

    def register_agent(self, name: str, agent):
        self.agents[name] = agent

    def _status(self, msg: str):
        print(msg)
        if self.on_status:
            self.on_status(msg)

    async def run(self, user_prompt: str) -> ProjectSpec:
        """Full pipeline from prompt to quote."""
        spec = ProjectSpec(prompt=user_prompt)

        # ── Step 1: Analyze requirements ──
        self._status(f"🧠 Analyzing: '{user_prompt}'")
        try:
            spec.requirements = await self._analyze_requirements(user_prompt)
            self._status(f"📋 Project: {spec.requirements.get('project_name', 'Unknown')}")
            self._status(f"   Components: {', '.join(spec.requirements.get('components_needed', []))}")
        except Exception as e:
            spec.errors.append(f"Requirements analysis failed: {e}")
            spec.status = "error"
            return spec

        # ── Step 2: Parts selection (BOM) ──
        self._status("\n🔩 Selecting parts...")
        msg = AgentMessage("orchestrator", "parts", "select_parts", spec.requirements)
        bom = await self._dispatch(msg)
        if isinstance(bom, list) and bom:
            spec.bom = bom
            total_parts_cost = sum(
                p.get("price", p.get("estimated_price", 0)) * p.get("quantity", 1)
                for p in bom
            )
            self._status(f"   ✅ {len(bom)} parts selected (₹{total_parts_cost:.0f} estimated)")
        else:
            spec.errors.append("Parts selection returned empty BOM")

        # ── Step 3: PCB Design ──
        self._status("\n🔌 Designing PCB...")
        msg = AgentMessage("orchestrator", "pcb", "design_pcb", {
            "requirements": spec.requirements,
            "bom": spec.bom,
        })
        pcb = await self._dispatch(msg)
        if isinstance(pcb, dict) and pcb:
            spec.pcb_design = pcb
            self._status(f"   ✅ PCB design generated")
        else:
            spec.errors.append("PCB design failed")

        # ── Step 4: 3D CAD ──
        self._status("\n📐 Generating 3D enclosure...")
        msg = AgentMessage("orchestrator", "cad", "generate_enclosure", {
            "requirements": spec.requirements,
            "bom": spec.bom,
            "pcb": spec.pcb_design or {},
        })
        cad = await self._dispatch(msg)
        if isinstance(cad, dict) and cad:
            spec.cad_files = cad.get("files", [])
            self._status(f"   ✅ {len(spec.cad_files)} CAD files generated")
        else:
            spec.errors.append("CAD generation failed")

        # ── Step 5: Assembly ──
        self._status("\n🔧 Creating assembly plan...")
        # Slim payload — assembly doesn't need full PCB/CAD data
        slim_bom = [{"name": p.get("name"), "quantity": p.get("quantity", 1)} for p in spec.bom]
        msg = AgentMessage("orchestrator", "assembler", "plan_assembly", {
            "requirements": spec.requirements,
            "bom": slim_bom,
            "pcb": {"has_pcb": bool(spec.pcb_design), "dimensions": (spec.pcb_design or {}).get("dimensions", {})},
            "cad": {"files": spec.cad_files},
        })
        assembly = await self._dispatch(msg)
        if isinstance(assembly, dict) and assembly:
            spec.assembly = assembly
            step_count = len(assembly.get("steps", []))
            self._status(f"   ✅ {step_count} assembly steps")
        else:
            spec.errors.append("Assembly plan failed")

        # ── Step 6: Quote ──
        self._status("\n💰 Calculating quote...")
        msg = AgentMessage("orchestrator", "quoter", "calculate_quote", {
            "bom": spec.bom,
            "cad": cad or {},
            "pcb": spec.pcb_design or {},
        })
        quote = await self._dispatch(msg)
        if isinstance(quote, dict) and quote:
            spec.quote = quote
            spec.total_cost = quote.get("total", 0)
            spec.delivery_estimate = quote.get("delivery", "")
            self._status(f"   ✅ Total: ₹{spec.total_cost:,.2f}")

        spec.status = "ready" if not spec.errors else "partial"
        self._status(f"\n{'✅' if spec.status == 'ready' else '⚠️'} Project {spec.status} — ₹{spec.total_cost:,.2f}")
        if spec.errors:
            for err in spec.errors:
                self._status(f"   ⚠ {err}")

        return spec

    async def _analyze_requirements(self, prompt: str) -> dict:
        """Use Claude to break down the user prompt into structured requirements."""
        response = self.client.messages.create(
            model=MODEL_REASONING,
            max_tokens=2000,
            system="""You are a hardware project analyzer. Given a user's description of what they want to build, extract structured requirements.

Return ONLY valid JSON (no markdown, no explanation):
{
    "project_name": "short name",
    "target_audience": "who is this for",
    "core_function": "what does it do",
    "components_needed": ["camera module", "microcontroller", "battery", ...],
    "size_constraint": "small|medium|large",
    "battery_powered": true/false,
    "wireless_needed": true/false,
    "display_needed": true/false,
    "estimated_complexity": "beginner|intermediate|advanced",
    "safety_requirements": ["rounded edges", ...],
    "special_notes": "anything else relevant"
}

Be specific with components_needed — use terms like "ESP32", "OV2640 camera module", "18650 battery", "OLED display", "PIR sensor" etc. Think about ALL the parts needed including passive components, connectors, and power regulation.""",
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_json_response(response.content[0].text)

    async def _dispatch(self, msg: AgentMessage) -> Any:
        """Dispatch a message to the target agent."""
        self.message_log.append(msg)
        agent = self.agents.get(msg.to_agent)
        if agent is None:
            self._status(f"   ⚠ Agent '{msg.to_agent}' not registered")
            msg.status = "error"
            msg.error = "Agent not registered"
            return {}

        msg.status = "in_progress"
        t0 = time.monotonic()
        try:
            result = await agent.handle(msg)
            msg.status = "done"
            msg.result = result
            msg.duration_ms = int((time.monotonic() - t0) * 1000)
            return result
        except Exception as e:
            msg.status = "error"
            msg.error = str(e)
            msg.duration_ms = int((time.monotonic() - t0) * 1000)
            self._status(f"   ❌ Agent '{msg.to_agent}' error: {e}")
            return {}
