# Semantic Router V3

Local semantic message router for multi-agent systems. Routes messages to the correct agent based on embeddings + keyword + context scoring. No external APIs, no cloud dependencies, works on ARM64.

## Performance

- **93%+ accuracy** on 41-query benchmark
- **~40ms** average latency, **0.78ms** cached
- **100% accuracy** with keyword override + embedding blend
- Runs on **Raspberry Pi 5** (ARM64)

## Architecture

Three-layer scoring system:
1. **Semantic layer** — nomic-embed-text embeddings via Ollama (60% weight)
2. **Keyword layer** — TF-IDF boosted matching (40% weight)
3. **Keyword override** — Strong pattern match bypasses scoring

```
Query → Embed + Keyword → Blend Scores → Override Check → Route
```

### Prefilter

Lightweight deterministic prefilter catches obvious patterns before semantic scoring:
- Tool invocation detection
- Repair/ops/research verb classification
- Health/monitoring disambiguation
- **84.5% deflection**, **100% alignment** on labeled corpus

### Shadow Mode

Run a planner alongside the live router to detect routing drift:
- Logs divergences between live and planned routes
- Dashboard aggregates match rate, correction rate, latencies
- **36.4% correction rate** on observed queries

## Files

| File | Description |
|------|-------------|
| `message_router_v3_base.py` | Core router logic (scoring, routes, benchmark) |
| `message-router-v3-api.py` | FastAPI HTTP API (6 endpoints) |
| `meta_routing_prefilter.py` | Deterministic prefilter engine |
| `meta_routing_prefilter_rules.json` | Declarative prefilter rules (external config) |
| `shared_route_vocabulary.py` | Centralized route maps and canonical routes |

## Quick Start

```bash
pip install -r message-router-v3-requirements.txt
python3 message-router-v3-api.py

# Test
curl -X POST http://localhost:8905/route \
  -H 'content-type: application/json' \
  -d '{"query": "restart the docker container"}'
```

### With Shadow Mode

```bash
ROUTER_SHADOW_ENABLED=1 \
ROUTER_SHADOW_LOG=/tmp/shadow.ndjson \
python3 message-router-v3-api.py
```

## Endpoints

- `POST /route` — Route a single query
- `POST /batch` — Route multiple queries
- `POST /benchmark` — Run full benchmark suite
- `GET /stats` — Router statistics
- `GET /routes` — List available routes
- `GET /health` — Health check

## Route → Agent Map

| Route | Agent |
|-------|-------|
| ops | Orion (SRE) |
| dev | Tachikoma |
| security | Aegis |
| experiment | Proto (Labs) |
| research | Specter |
| monitoring | Orion |
| infra | Orion |
| agent_comm | Tachikoma |

## Requirements

- Python 3.10+
- Ollama with `nomic-embed-text` model (for semantic scoring)
- Works without Ollama (BM25 fallback)

## License

MIT
