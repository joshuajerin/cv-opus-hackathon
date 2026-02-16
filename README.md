# Hardware Builder

Multi-agent system that converts natural language into complete hardware project specifications. Prompt → BOM → PCB → 3D enclosure → assembly guide → USD quote.

Built on Anthropic Claude Opus. 14,758-component database. Agent-to-agent protocol. One-click OpenClaw skill.

```
"autonomous drone" → 22 parts, 47 PCB connections, 11 assembly steps, $303.90
```

---

## Architecture

```
                            ┌─────────────────┐
                            │    FastAPI       │
                 ┌──────────│  /build          │──────────┐
                 │          │  /a2a/build      │          │
                 │          │  /a2a/discover   │          │
                 │          └────────┬─────────┘          │
                 │                   │                     │
          ┌──────▼──────┐   ┌───────▼────────┐   ┌───────▼──────┐
          │  React UI   │   │  ORCHESTRATOR  │   │  A2A Agent   │
          │  CORTEX     │   │                │   │  Protocol    │
          │  frontend   │   │  Claude Opus   │   │  /a2a/*      │
          └─────────────┘   └───────┬────────┘   └──────────────┘
                                    │
              ┌─────────┬───────────┼───────────┬─────────┐
              │         │           │           │         │
         ┌────▼──┐ ┌────▼──┐ ┌─────▼──┐ ┌─────▼──┐ ┌────▼───┐
         │ PARTS │ │  PCB  │ │  CAD   │ │  ASM   │ │ QUOTER │
         │ AGENT │ │ AGENT │ │ AGENT  │ │ AGENT  │ │ AGENT  │
         │       │ │       │ │        │ │        │ │        │
         │ FTS5  │ │Circuit│ │OpenSCAD│ │ Steps  │ │  Math  │
         │ +LLM  │ │Schema │ │ Body   │ │ Tools  │ │ No LLM │
         │ BOM   │ │Layout │ │ Lid    │ │ Guide  │ │ USD    │
         └───┬───┘ └───┬───┘ └───┬────┘ └────────┘ └────────┘
             │         │         │
        ┌────▼────┐ ┌──▼───┐ ┌──▼───┐
        │ SQLite  │ │KiCad │ │.scad │
        │ 14,758  │ │.kicad│ │.stl  │
        │ FTS5    │ │_sch  │ │      │
        └─────────┘ └──────┘ └──────┘
```

## Pipeline Specification

| Stage | Agent | Model | Avg Latency | Input | Output |
|-------|-------|-------|-------------|-------|--------|
| 1 | Orchestrator | `claude-opus-4-6` | 10.2s | `prompt: string` | `RequirementsSpec` |
| 2 | Parts Agent | `claude-opus-4-6` | 29.6s | `RequirementsSpec` | `BOMItem[]` |
| 3 | PCB Agent | `claude-opus-4-6` | 118.4s | `RequirementsSpec + BOM` | `PCBDesign` |
| 4 | CAD Agent | `claude-opus-4-6` | 64.0s | `RequirementsSpec + BOM + PCB` | `CADFile[]` |
| 5 | Assembly Agent | `claude-opus-4-6` | 71.9s | `RequirementsSpec + BOM + PCB + CAD` | `AssemblyGuide` |
| 6 | Quoter Agent | deterministic | <1ms | `BOM + PCB + CAD` | `Quote (USD)` |

**Total pipeline latency:** ~295s (sequential execution)

## Agent Communication Protocol

Agents communicate via typed `AgentMessage` envelopes:

```python
@dataclass
class AgentMessage:
    from_agent: str           # "orchestrator"
    to_agent: str             # "parts" | "pcb" | "cad" | "assembler" | "quoter"
    task: str                 # "select_parts" | "design_pcb" | ...
    payload: dict             # task-specific input data
    status: str = "pending"   # pending → in_progress → done | error
    result: Any = None
    error: str | None = None
    duration_ms: int = 0
```

Dispatch is sequential. Each agent receives the accumulated outputs of prior agents:

```
orchestrator._analyze_requirements(prompt)
    → dispatch("parts",     {requirements})
    → dispatch("pcb",       {requirements, bom})
    → dispatch("cad",       {requirements, bom, pcb_design})
    → dispatch("assembler", {requirements, bom, pcb_design, cad_files})
    → dispatch("quoter",    {bom, pcb_design, cad_files})
```

## Database

### Schema

```sql
CREATE TABLE parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    sku TEXT,
    price REAL,                  -- source currency: INR
    currency TEXT DEFAULT 'INR',
    in_stock INTEGER DEFAULT 1,
    description TEXT,
    specs TEXT,                  -- JSON blob
    image_url TEXT,
    category_id INTEGER REFERENCES categories(id),
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE parts_fts USING fts5(
    name, description, specs,
    content=parts, content_rowid=id
);
```

### Statistics

| Metric | Value |
|--------|-------|
| Total products | 14,758 |
| Priced products | 1,587 |
| Categories | 561 |
| Price range (INR) | ₹1 – ₹683,399 |
| FTS5 index | name + description + specs |
| Source | robu.in via Wayback Machine |

### Search Strategy

The Parts Agent uses a two-tier search:

1. **FTS5 full-text** — `WHERE parts_fts MATCH ?` with BM25 ranking
2. **LIKE fallback** — `WHERE name LIKE ? OR description LIKE ?`

Claude evaluates candidate parts against requirements and selects an optimal BOM with quantities and rationale.

## PCB Design Pipeline

Three sequential LLM calls:

### 1. Circuit Design
```json
{
  "connections": [
    {"from": "Flight_Controller.PPM", "to": "Receiver.PPM_OUT", "type": "PWM"},
    {"from": "Flight_Controller.MOTOR1", "to": "ESC_1.SIGNAL", "type": "PWM"}
  ],
  "power_rails": [
    {"name": "VBAT", "voltage": "11.1-16.8V", "source": "LiPo Battery"}
  ]
}
```

### 2. KiCad Schematic
Generates `.kicad_sch` format with:
- Component symbols and pin mappings
- Wire connections from circuit design
- Power flags and ground references

### 3. Board Layout
```json
{
  "layers": 4,
  "dimensions_mm": {"width": 80, "height": 60},
  "mounting_holes": 4,
  "trace_width_mm": {"signal": 0.25, "power": 0.5}
}
```

## CAD Generation

Parametric OpenSCAD with component-specific mounting:

```openscad
// Auto-generated body.scad
module enclosure_body() {
    difference() {
        // Outer shell with rounded edges
        minkowski() {
            cube([body_w - 2*fillet, body_d - 2*fillet, body_h - fillet]);
            sphere(r=fillet);
        }
        // Interior cavity
        translate([wall, wall, wall])
            cube([body_w - 2*wall, body_d - 2*wall, body_h]);
        // Port cutouts, ventilation slots
        ...
    }
    // Mounting posts for PCB
    for (pos = mounting_positions) {
        translate(pos) cylinder(h=post_h, r=post_r);
    }
}
```

Compiles to `.stl` when OpenSCAD CLI is available. Otherwise saves `.scad` source only.

## Cost Calculation

The Quoter Agent uses deterministic arithmetic — no LLM call:

```
parts_usd   = Σ(part.price_inr × quantity) × 0.012
pcb_usd     = (150 + max(0, board_area_cm² - 25) × 2.0) × 0.012
print_usd   = weight_grams × 5.0 × 0.012
ship_usd    = 80 × 0.012
platform    = subtotal × 0.10
total       = subtotal + platform
```

Conversion rate: `1 USD = 83.3 INR` (configurable in `quoter_agent.py`).

## API Reference

### `POST /build`

Build a hardware project from a prompt.

**Request:**
```json
{"prompt": "autonomous drone with GPS and FPV camera"}
```

**Response:** See [`schemas/build-response.json`](schemas/build-response.json)

### `POST /a2a/build`

Agent-to-Agent protocol endpoint. See [`docs/PROTOCOL.md`](docs/PROTOCOL.md).

```json
{
  "task": "hardware_build",
  "prompt": "autonomous drone",
  "callback_url": null,
  "context": {"session": "abc"}
}
```

### `GET /a2a/discover`

Capability advertisement for agent discovery.

### `GET /search?q=esp32&limit=20`

Full-text search against parts database.

### `GET /stats`

Database statistics (part count, category count, price range).

### `GET /health`

Server + database health check.

### `GET /docs`

Interactive OpenAPI documentation (Swagger UI).

### `GET /redoc`

ReDoc API documentation.

## Frontend

Single-page CORTEX-inspired interface. React 19 + TypeScript + Tailwind v4.

### Components

| Component | Lines | Purpose |
|-----------|-------|---------|
| `App.tsx` | 555 | Main layout, state machine, stage cards, detail renderers |
| `MatrixPanel.tsx` | 95 | Left panel: hex cycling (idle) / agent log (build) |
| `PartsGraph.tsx` | 230 | Force-directed constellation graph (canvas 2D) |
| `LiveGraph.tsx` | 55 | Animated waveform display (canvas 2D) |

### PartsGraph — Force-Directed Layout

Physics simulation at 60fps:

```
For each node:
  F_gravity   = (center - pos) × 0.00025
  F_repulsion = Σ 350 / dist² (from all other nodes)
  F_spring    = (dist - 110) × 0.0006 (connected nodes only)
  F_drift     = random × 0.05
  velocity    = (velocity + F_total) × 0.97  (damped)
  position    += velocity  (clamped to ±1.3)
```

Nodes sized by `3 + log(price) / log(maxPrice) × 10`. Edges mapped from PCB connections via component name fuzzy matching. Hover highlights connected subgraph.

### Build: 217KB gzip'd

```
dist/index.html              0.84 KB
dist/assets/index-*.css     13.30 KB (3.56 KB gzip)
dist/assets/index-*.js     217.13 KB (68.10 KB gzip)
```

## Local Setup

### Prerequisites

- Python 3.12+
- Node.js 22+ (for frontend build)
- Anthropic API key

### Install

```bash
git clone https://github.com/joshuajerin/cv-opus-hackathon.git
cd cv-opus-hackathon

# Python dependencies
pip install -r requirements.txt

# Frontend
cd frontend && npm install && npm run build && cd ..

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...
```

### Build the Parts Database

The database isn't included in the repo (7.7MB). Build it from Wayback Machine:

```bash
make scrape          # Full scrape (~14,758 products, takes ~2 hours)
make db-rebuild-fts  # Rebuild FTS5 index after scraping
make db-stats        # Verify: should show ~14,758 parts
```

### Run

```bash
# Web UI + API
make serve
# → http://localhost:8000

# CLI build
make run PROMPT="autonomous drone"

# Memory-efficient staged build (for <8GB RAM machines)
make run-staged PROMPT="autonomous drone"
```

### Docker

```bash
docker build -t hardware-builder .
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v ./parts.db:/app/parts.db \
  hardware-builder
```

## OpenClaw Skill

One-click integration for any OpenClaw deployment:

```bash
# Install as skill
./install.sh

# The A2A endpoint at /a2a/build allows any OpenClaw agent
# to invoke hardware builds programmatically
```

See [`SKILL.md`](SKILL.md) for detailed integration instructions.

## Project Structure

```
├── SKILL.md                    # OpenClaw skill manifest
├── install.sh                  # One-click setup
├── Makefile                    # Build automation (17 targets)
├── Dockerfile                  # Multi-stage container build
├── requirements.txt            # Python: anthropic, fastapi, uvicorn, aiohttp, bs4
│
├── src/
│   ├── config.py               # Auto-loads Anthropic key from OpenClaw auth store
│   ├── agents/
│   │   ├── orchestrator.py     # Pipeline coordinator (252 lines)
│   │   ├── parts_agent.py      # FTS5 search + LLM selection (178 lines)
│   │   ├── pcb/
│   │   │   └── pcb_agent.py    # 3-step PCB pipeline (136 lines)
│   │   ├── cad/
│   │   │   └── cad_agent.py    # OpenSCAD generation (153 lines)
│   │   ├── assembler/
│   │   │   └── assembly_agent.py  # Build guide (73 lines)
│   │   └── quoter/
│   │       └── quoter_agent.py # Deterministic USD pricing (95 lines)
│   ├── api/
│   │   └── server.py           # FastAPI REST + A2A (180 lines)
│   ├── db/
│   │   └── schema.py           # SQLite + FTS5 schema (90 lines)
│   └── scraper/
│       ├── wayback_scraper.py  # Wayback Machine scraper with resume
│       └── robu_scraper.py     # Direct scraper (blocked by Cloudflare)
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx             # Single-page build interface
│   │   ├── components/
│   │   │   ├── MatrixPanel.tsx  # Agent activity log
│   │   │   ├── PartsGraph.tsx   # Force-directed constellation
│   │   │   └── LiveGraph.tsx    # Waveform canvas
│   │   └── lib/
│   │       ├── api.ts          # HTTP client
│   │       └── types.ts        # TypeScript interfaces
│   └── dist/                   # Production build (served by FastAPI)
│
├── schemas/
│   ├── build-request.json      # JSON Schema: input
│   ├── build-response.json     # JSON Schema: output
│   └── a2a-envelope.json       # JSON Schema: A2A protocol
│
├── docs/
│   ├── ARCHITECTURE.md         # System design + data flow
│   └── PROTOCOL.md             # A2A protocol specification
│
├── run.py                      # CLI runner (single process)
└── run_staged.py               # Memory-efficient staged runner
```

## Performance

Benchmarked on Ubuntu 22.04, 16GB RAM, Claude Opus via API:

| Build | Parts | Connections | Steps | Total Cost | Pipeline Time |
|-------|-------|-------------|-------|------------|---------------|
| Kids Camera | 19 | 14 | 8 | $38.81 | 283s |
| Autonomous Drone | 22 | 47 | 11 | $303.90 | 294s |

Memory usage peaks at ~2GB during PCB agent (longest stage). The staged runner (`run_staged.py`) keeps peak memory under 500MB by running each agent in a subprocess.
