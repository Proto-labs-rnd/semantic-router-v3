# Message Router V3 — Runbook

## Démarrage
```bash
# Natif
python3 tools/message-router-v3-api.py

# Docker
docker build -t router-v3 -f tools/Dockerfile.router-v3 tools/
docker run -d --name router-v3 -p 127.0.0.1:8905:8905 --network host router-v3
```

## Arrêt
```bash
# Natif
fuser -k 8905/tcp

# Docker
docker stop router-v3
```

## Santé
```bash
curl -s http://127.0.0.1:8905/health
```

## Test complet
```bash
bash tools/test-router-v3.sh
```

## Benchmark
```bash
curl -s http://127.0.0.1:8905/benchmark -X POST
```

## Dépendances
- Python 3.10+
- Ollama avec nomic-embed-text (port 11434)
- starlette, uvicorn, requests, aiohttp

## Failure modes
- **Ollama down** → Service démarre mais `/health` retourne `"ollama": "unhealthy"`. Routing utilise le cache disque si dispo.
- **Ollama timeout** → Requête individuelle fallback sur keyword matching.
- **Port 8905 pris** → Erreur au démarrage. Libérer avec `fuser -k 8905/tcp`.

## Ports
- API : 127.0.0.1:8905 (bind local uniquement)
- Ollama : 127.0.0.1:11434

## Sécurité
- Bind local uniquement (127.0.0.1)
- Pas d'auth (usage interne uniquement)
- Pas d'exposition réseau
