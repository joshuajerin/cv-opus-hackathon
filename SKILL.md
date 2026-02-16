# Hardware Builder — OpenClaw Skill

## What This Does

Multi-agent hardware design system. Give it a prompt ("autonomous drone", "weather station"), get back:
- **BOM** — parts list from 14,758-component database (prices in USD)
- **PCB** — circuit design + KiCad schematic + board layout
- **Enclosure** — parametric OpenSCAD 3D-printable files
- **Assembly** — step-by-step build guide with tools + time estimates
- **Quote** — full cost breakdown in USD

## Quick Start

```bash
# From the skill directory:
./install.sh

# Run a build:
make run PROMPT="autonomous drone"

# Start the web UI + API:
make serve
# → http://localhost:8000
```

## Using as an Agent

### REST API

```bash
curl -X POST http://localhost:8000/build \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "camera for a kid"}'
```

### A2A Protocol

```bash
# Discover capabilities
curl http://localhost:8000/a2a/discover

# Build via A2A
curl -X POST http://localhost:8000/a2a/build \
  -H 'Content-Type: application/json' \
  -d '{"task": "hardware_build", "prompt": "garden weather station"}'
```

### From Another OpenClaw Agent

If the Hardware Builder server is running, any OpenClaw agent can call it:

```
User: "Design me an autonomous drone"

Agent thinks:
  → POST http://localhost:8000/a2a/build {"task": "hardware_build", "prompt": "autonomous drone"}
  → Receives full project spec with BOM, PCB, enclosure, assembly, quote
  → Presents results to user
```

## Requirements

- Python 3.12+
- Node.js 22+ (frontend build only)
- Anthropic API key (set `ANTHROPIC_API_KEY` env var)
- ~8GB RAM for Opus model calls (or use `run_staged.py` for memory-constrained environments)

## Configuration

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or if running inside OpenClaw, it auto-loads from the auth profile at
`~/.openclaw/agents/main/agent/auth-profiles.json`.

## Pipeline Stages

| # | Agent      | Model | Time  | Output                     |
|---|------------|-------|-------|----------------------------|
| 1 | Orchestrator | Opus  | ~10s  | Structured requirements    |
| 2 | Parts      | Opus  | ~30s  | BOM with prices            |
| 3 | PCB        | Opus  | ~120s | Circuit + schematic + layout |
| 4 | CAD        | Opus  | ~60s  | OpenSCAD body + lid        |
| 5 | Assembly   | Opus  | ~70s  | Step-by-step guide         |
| 6 | Quoter     | None  | <1ms  | USD cost breakdown         |

**Total pipeline: ~5 minutes per build**

## File Structure

```
src/agents/orchestrator.py    — Pipeline coordination + Claude API
src/agents/parts_agent.py     — FTS5 search + LLM BOM selection
src/agents/pcb/pcb_agent.py   — Circuit → schematic → layout
src/agents/cad/cad_agent.py   — OpenSCAD parametric generation
src/agents/assembler/         — Build guide generation
src/agents/quoter/            — Deterministic USD pricing
src/api/server.py             — FastAPI REST + A2A endpoints
src/db/schema.py              — SQLite schema + FTS5 helpers
frontend/                     — React + TypeScript CORTEX UI
schemas/                      — JSON Schema definitions
docs/                         — Architecture + protocol specs
```
