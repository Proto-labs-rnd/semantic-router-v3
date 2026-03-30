#!/usr/bin/env python3
"""Import the proven V3 router"""

"""
Production Message Router V3 — HTTP API Wrapper

Wraps the proven Domain-Augmented Router V3 (100% accuracy) 
as a production HTTP service for the Message Bus.

Usage:
  python3 message-router-v3-api.py              # Start server
  curl -X POST localhost:8905/route -d '{"query":"déploie monitoring"}'  # Route query
"""

import os
import sys
import json
import time
import logging
import importlib.util
from pathlib import Path
from dataclasses import asdict

# Import the proven V3 router
sys.path.insert(0, str(Path(__file__).parent))
from message_router_v3_base import DomainAugmentedRouter, ROUTE_CONCEPTS  # noqa: E402
from shared_route_vocabulary import ROUTE_AGENT_MAP as _SHARED_ROUTE_AGENT_MAP, DEFAULT_AGENT, agent_for  # noqa: E402

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware

# ── Config ───────────────────────────────────────────────────
PORT = int(os.environ.get("ROUTER_PORT", "8905"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "10"))
API_TOKEN = os.environ.get("ROUTER_API_TOKEN", "")
SHADOW_ENABLED = os.environ.get("ROUTER_SHADOW_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
SHADOW_TOP_K = int(os.environ.get("ROUTER_SHADOW_TOP_K", "5"))
SHADOW_LOG_PATH = Path(os.environ.get("ROUTER_SHADOW_LOG", "/tmp/planner-shadow.ndjson"))
PREFILTER_SHADOW_ENABLED = os.environ.get("PREFILTER_SHADOW_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
PREFILTER_SHADOW_LOG_PATH = Path(os.environ.get("PREFILTER_SHADOW_LOG", "/tmp/prefilter-shadow.ndjson"))

# Route → Agent mapping — imported from shared vocabulary
ROUTE_AGENT_MAP = {**_SHARED_ROUTE_AGENT_MAP, "unknown": DEFAULT_AGENT}

# Structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
log = logging.getLogger("router-v3-api")

# ── Ollama health check ──────────────────────────────────────
def check_ollama():
    """Check if Ollama is reachable"""
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=OLLAMA_TIMEOUT)
        return r.status_code == 200
    except Exception as e:
        log.warning(f"Ollama health check failed: {e}")
        return False

# ── API auth middleware ──────────────────────────────────────
def check_auth(request):
    """Simple token auth if ROUTER_API_TOKEN is set"""
    if not API_TOKEN:
        return True  # No auth required
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:] == API_TOKEN
    return request.query_params.get("token", "") == API_TOKEN

# ── Ollama Health Check ──────────────────────────────────────
def check_ollama_health():
    """Check if Ollama is reachable and nomic-embed-text is available."""
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            has_nomic = any("nomic" in m for m in models)
            return {"reachable": True, "nomic_embed_available": has_nomic}
        return {"reachable": False, "status_code": r.status_code}
    except Exception as e:
        return {"reachable": False, "error": str(e)[:100]}

# ── Router Instance ──────────────────────────────────────────
router = DomainAugmentedRouter()
_initialized = False
_planner = None
_planner_error = None
_prefilter_module = None
_prefilter_error = None

def ensure_initialized():
    global _initialized
    if not _initialized:
        log.info("Initializing router centroids...")
        router.initialize()
        _initialized = True
        log.info("Router initialized!")


def load_planner_class():
    planner_path = Path(__file__).parent / "query-router-integration.py"
    spec = importlib.util.spec_from_file_location("query_router_integration", planner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load planner module from {planner_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.IntegratedQueryRouter


def load_prefilter_module():
    """Load prefilter module — prefer direct import, fallback to dynamic."""
    try:
        from meta_routing_prefilter import decide_prefilter as _dp, load_registry as _lr
        # Return a namespace-like object with the expected attributes
        import types
        mod = types.SimpleNamespace(decide_prefilter=_dp, load_registry=_lr)
        return mod
    except ImportError:
        prefilter_path = Path(__file__).parent / "meta_routing_prefilter.py"
        spec = importlib.util.spec_from_file_location("meta_routing_prefilter", prefilter_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load prefilter module from {prefilter_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


def ensure_planner():
    global _planner, _planner_error
    if _planner is None and _planner_error is None:
        try:
            PlannerClass = load_planner_class()
            _planner = PlannerClass()
            log.info("Planner shadow mode initialized")
        except Exception as exc:
            _planner_error = str(exc)
            log.warning(f"Planner shadow unavailable: {exc}")
    return _planner

def ensure_prefilter():
    global _prefilter_module, _prefilter_error
    if _prefilter_module is None and _prefilter_error is None:
        try:
            _prefilter_module = load_prefilter_module()
            log.info("Prefilter shadow mode initialized")
        except Exception as exc:
            _prefilter_error = str(exc)
            log.warning(f"Prefilter shadow unavailable: {exc}")
    return _prefilter_module


def shadow_enabled_for_request(body):
    if not SHADOW_ENABLED:
        return False
    return body.get("shadow", True) is not False


async def parse_json_body(request):
    try:
        return await request.json()
    except json.JSONDecodeError:
        return None


def append_shadow_log(record, path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.warning(f"Failed to append shadow log {path}: {exc}")

# ── Track stats ──────────────────────────────────────────────
_total = 0
_route_counts = {}
_method_counts = {}
_shadow_total = 0
_shadow_match = 0
_shadow_action_counts = {}
_shadow_corrections = {}
_prefilter_shadow_total = 0
_prefilter_shadow_match = 0
_prefilter_shadow_rules = {}
_prefilter_shadow_routes = {}

def track_result(result):
    global _total
    _total += 1
    _route_counts[result.route] = _route_counts.get(result.route, 0) + 1
    _method_counts[result.method] = _method_counts.get(result.method, 0) + 1


def track_shadow(live_route, plan):
    global _shadow_total, _shadow_match
    resolved_route = plan["route"]["resolved"]
    action_type = plan["action"]["type"]
    _shadow_total += 1
    _shadow_action_counts[action_type] = _shadow_action_counts.get(action_type, 0) + 1
    key = f"{live_route}->{resolved_route}"
    _shadow_corrections[key] = _shadow_corrections.get(key, 0) + 1
    if resolved_route == live_route:
        _shadow_match += 1

def track_prefilter_shadow(record):
    global _prefilter_shadow_total, _prefilter_shadow_match
    comparison = record.get("comparison", {})
    prefilter = record.get("prefilter", {})
    live_route = comparison.get("live_route") or record.get("live", {}).get("route") or "unknown"
    final_route = comparison.get("prefilter_route") or live_route
    rule = prefilter.get("rule") or "unknown"
    _prefilter_shadow_total += 1
    _prefilter_shadow_rules[rule] = _prefilter_shadow_rules.get(rule, 0) + 1
    key = f"{live_route}->{final_route}"
    _prefilter_shadow_routes[key] = _prefilter_shadow_routes.get(key, 0) + 1
    if comparison.get("match"):
        _prefilter_shadow_match += 1


def run_shadow_plan(query, live_route, agent, confidence, method, live_latency_ms):
    planner = ensure_planner()
    shadow_started = time.time()
    if planner is None:
        payload = {
            "enabled": True,
            "available": False,
            "error": _planner_error or "planner unavailable",
        }
        log.info(
            "shadow query=%r live=%s planner=%s match=%s action=%s tool=%s latency=%sms",
            query,
            live_route,
            payload.get("resolved_route"),
            payload.get("match"),
            payload.get("action_type"),
            payload.get("tool"),
            payload.get("latency_ms"),
        )
        return payload

    try:
        plan = planner.plan(query, top_k=SHADOW_TOP_K)
        shadow_elapsed = round((time.time() - shadow_started) * 1000, 2)
        top_tool = plan["tool_candidates"][0]["name"] if plan.get("tool_candidates") else None
        payload = {
            "enabled": True,
            "available": True,
            "base_route": plan["route"]["base"],
            "resolved_route": plan["route"]["resolved"],
            "match": plan["route"]["resolved"] == live_route,
            "action_type": plan["action"]["type"],
            "tool": top_tool,
            "latency_ms": shadow_elapsed,
        }
        track_shadow(live_route, plan)
        append_shadow_log({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mode": "shadow",
            "query": query,
            "live": {
                "route": live_route,
                "agent": agent,
                "confidence": round(confidence, 4),
                "method": method,
                "latency_ms": live_latency_ms,
            },
            "shadow": {
                "route": plan["route"],
                "agent": plan["agent"],
                "action": plan["action"],
                "tool_candidates": plan["tool_candidates"],
                "latency_ms": shadow_elapsed,
            },
            "comparison": {
                "match": plan["route"]["resolved"] == live_route,
                "corrected": plan["route"]["resolved"] != live_route,
                "live_route": live_route,
                "planner_route": plan["route"]["resolved"],
            },
        }, SHADOW_LOG_PATH)
        log.info(
            "shadow query=%r live=%s planner=%s match=%s action=%s tool=%s latency=%sms",
            query,
            live_route,
            payload.get("resolved_route"),
            payload.get("match"),
            payload.get("action_type"),
            payload.get("tool"),
            payload.get("latency_ms"),
        )
        return payload
    except Exception as exc:
        payload = {
            "enabled": True,
            "available": False,
            "error": str(exc),
        }
        log.info(
            "shadow query=%r live=%s planner=%s match=%s action=%s tool=%s latency=%sms",
            query,
            live_route,
            payload.get("resolved_route"),
            payload.get("match"),
            payload.get("action_type"),
            payload.get("tool"),
            payload.get("latency_ms"),
        )
        return payload


def run_prefilter_shadow(query, live_route, agent, confidence, method, live_latency_ms):
    module = ensure_prefilter()
    shadow_started = time.time()
    if module is None:
        payload = {
            "enabled": True,
            "available": False,
            "error": _prefilter_error or "prefilter unavailable",
        }
        log.info(
            "prefilter_shadow query=%r live=%s prefilter=%s match=%s rule=%s latency=%sms",
            query,
            live_route,
            payload.get("final_route"),
            payload.get("match"),
            payload.get("rule"),
            payload.get("latency_ms"),
        )
        return payload

    try:
        decision = module.decide_prefilter({"query": query})
        shadow_elapsed = round((time.time() - shadow_started) * 1000, 2)
        final_route = decision.route or live_route
        matched = final_route == live_route
        corrected = decision.route is not None and final_route != live_route
        payload = {
            "enabled": True,
            "available": True,
            "route": decision.route,
            "final_route": final_route,
            "rule": decision.rule,
            "detail": decision.detail,
            "match": matched,
            "corrected": corrected,
            "latency_ms": shadow_elapsed,
        }
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "mode": "prefilter_shadow",
            "query": query,
            "live": {
                "route": live_route,
                "agent": agent,
                "confidence": round(confidence, 4),
                "method": method,
                "latency_ms": live_latency_ms,
            },
            "prefilter": {
                "route": decision.route,
                "final_route": final_route,
                "rule": decision.rule,
                "detail": decision.detail,
                "latency_ms": shadow_elapsed,
            },
            "comparison": {
                "match": matched,
                "corrected": corrected,
                "live_route": live_route,
                "prefilter_route": final_route,
            },
        }
        track_prefilter_shadow(record)
        append_shadow_log(record, PREFILTER_SHADOW_LOG_PATH)
        log.info(
            "prefilter_shadow query=%r live=%s prefilter=%s match=%s rule=%s latency=%sms",
            query,
            live_route,
            payload.get("final_route"),
            payload.get("match"),
            payload.get("rule"),
            payload.get("latency_ms"),
        )
        return payload
    except Exception as exc:
        payload = {
            "enabled": True,
            "available": False,
            "error": str(exc),
        }
        log.info(
            "prefilter_shadow query=%r live=%s prefilter=%s match=%s rule=%s latency=%sms",
            query,
            live_route,
            payload.get("final_route"),
            payload.get("match"),
            payload.get("rule"),
            payload.get("latency_ms"),
        )
        return payload


def run_shadow_tasks(query, live_route, agent, confidence, method, live_latency_ms):
    if SHADOW_ENABLED:
        run_shadow_plan(query, live_route, agent, confidence, method, live_latency_ms)
    if PREFILTER_SHADOW_ENABLED:
        run_prefilter_shadow(query, live_route, agent, confidence, method, live_latency_ms)


# ── Endpoints ────────────────────────────────────────────────

async def health(request):
    ollama_ok = check_ollama()
    return JSONResponse({
        "status": "ok" if ollama_ok else "degraded",
        "service": "message-router-v3",
        "version": "1.2.0",
        "initialized": _initialized,
        "total_queries": _total,
        "ollama": {"url": OLLAMA_URL, "healthy": ollama_ok},
        "bind": "127.0.0.1",
        "shadow": {
            "enabled": SHADOW_ENABLED,
            "planner_ready": _planner is not None,
            "planner_error": _planner_error,
            "log_path": str(SHADOW_LOG_PATH),
            "prefilter_enabled": PREFILTER_SHADOW_ENABLED,
            "prefilter_ready": _prefilter_module is not None,
            "prefilter_error": _prefilter_error,
            "prefilter_log_path": str(PREFILTER_SHADOW_LOG_PATH),
        },
    })

async def route_message(request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    ensure_initialized()
    body = await parse_json_body(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    query = body.get("query", "")
    if not query:
        return JSONResponse({"error": "Missing 'query'"}, status_code=400)
    
    t0 = time.time()
    result = router.route(query)
    elapsed = round((time.time() - t0) * 1000, 2)
    track_result(result)
    
    agent = ROUTE_AGENT_MAP.get(result.route, "tachikoma")

    shadow_payload = None
    prefilter_shadow_payload = None
    response_background = None
    shadow_requested = shadow_enabled_for_request(body)
    if shadow_requested and (SHADOW_ENABLED or PREFILTER_SHADOW_ENABLED):
        if body.get("debug_shadow"):
            if SHADOW_ENABLED:
                shadow_payload = run_shadow_plan(
                    query,
                    result.route,
                    agent,
                    float(result.confidence),
                    result.method,
                    elapsed,
                )
            if PREFILTER_SHADOW_ENABLED:
                prefilter_shadow_payload = run_prefilter_shadow(
                    query,
                    result.route,
                    agent,
                    float(result.confidence),
                    result.method,
                    elapsed,
                )
        else:
            response_background = BackgroundTask(
                run_shadow_tasks,
                query,
                result.route,
                agent,
                float(result.confidence),
                result.method,
                elapsed,
            )
    
    # Structured log
    log.info(f"route query={query!r} → {result.route} agent={agent} conf={result.confidence:.4f} method={result.method} latency={elapsed}ms")
    
    response = {
        "route": result.route,
        "agent": agent,
        "confidence": round(result.confidence, 4),
        "method": result.method,
        "latency_ms": elapsed,
    }
    if body.get("debug_shadow"):
        if shadow_payload is not None:
            response["shadow"] = shadow_payload
        if prefilter_shadow_payload is not None:
            response["prefilter_shadow"] = prefilter_shadow_payload
    return JSONResponse(response, background=response_background)

async def batch_route(request):
    ensure_initialized()
    body = await parse_json_body(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    queries = body.get("queries", [])
    results = []
    for q in queries:
        r = router.route(q)
        track_result(r)
        results.append({
            "query": q,
            "route": r.route,
            "agent": ROUTE_AGENT_MAP.get(r.route, "tachikoma"),
            "confidence": round(r.confidence, 4),
            "method": r.method,
            "latency_ms": round(r.latency_ms, 2),
        })
    return JSONResponse({"results": results, "count": len(results)})

async def get_stats(request):
    return JSONResponse({
        "total_queries": _total,
        "route_distribution": _route_counts,
        "method_distribution": _method_counts,
        "shadow": {
            "enabled": SHADOW_ENABLED,
            "total": _shadow_total,
            "matches": _shadow_match,
            "match_rate": round((_shadow_match / _shadow_total) * 100, 1) if _shadow_total else None,
            "action_distribution": _shadow_action_counts,
            "route_pairs": _shadow_corrections,
            "planner_error": _planner_error,
            "log_path": str(SHADOW_LOG_PATH),
        },
        "prefilter_shadow": {
            "enabled": PREFILTER_SHADOW_ENABLED,
            "total": _prefilter_shadow_total,
            "matches": _prefilter_shadow_match,
            "match_rate": round((_prefilter_shadow_match / _prefilter_shadow_total) * 100, 1) if _prefilter_shadow_total else None,
            "rule_distribution": _prefilter_shadow_rules,
            "route_pairs": _prefilter_shadow_routes,
            "prefilter_error": _prefilter_error,
            "log_path": str(PREFILTER_SHADOW_LOG_PATH),
        },
        "initialized": _initialized,
        "routes": list(ROUTE_CONCEPTS.keys()),
        "route_agent_map": ROUTE_AGENT_MAP,
    })

async def list_routes(request):
    return JSONResponse({
        "routes": {
            route: ROUTE_AGENT_MAP.get(route, "unknown")
            for route in ROUTE_CONCEPTS.keys()
        }
    })

async def benchmark(request):
    """Run the full 41-query benchmark and return results."""
    ensure_initialized()
    
    test_cases = [
        ("Check monitoring dashboard", "monitoring"),
        ("Surveille les services", "monitoring"),
        ("Grafana alerts not working", "monitoring"),
        ("Show me the metrics", "monitoring"),
        ("Alertes de monitoring", "monitoring"),
        ("Security alert: suspicious activity", "security_alert"),
        ("Vérifie le firewall", "security_alert"),
        ("SSL certificate expired", "security_alert"),
        ("Trivy scan found vulnerabilities", "security_alert"),
        ("Sécurise le serveur", "security_alert"),
        ("Debug the API endpoint", "dev_request"),
        ("Fix the bug in handler", "dev_request"),
        ("Write a new script", "dev_request"),
        ("Code review needed", "dev_request"),
        ("Développe une nouvelle feature", "dev_request"),
        ("Deploy the new stack", "ops_request"),
        ("Redémarre le container", "ops_request"),
        ("Backup the database", "ops_request"),
        ("Déploie monitoring sur cortex", "ops_request"),
        ("Installe le nouveau service", "ops_request"),
        ("Configure le reverse proxy", "ops_request"),
        ("Research best practices for Docker", "research_query"),
        ("How to setup WireGuard VPN", "research_query"),
        ("Explain the architecture", "research_query"),
        ("Compare Ollama vs vLLM", "research_query"),
        ("Veille technologique", "research_query"),
        ("Test the new embedding approach", "experiment_request"),
        ("Benchmark the model performance", "experiment_request"),
        ("Try the prototype", "experiment_request"),
        ("Expérimente avec nomic-embed", "experiment_request"),
        ("Validate the POC", "experiment_request"),
        ("Server CPU usage too high", "infrastructure_health"),
        ("Network latency issues", "infrastructure_health"),
        ("Disk space running low", "infrastructure_health"),
        ("Docker container status check", "infrastructure_health"),
        ("RPi temperature monitoring", "infrastructure_health"),
        ("Route this message to Tachikoma", "agent_communication"),
        ("Send message via bus", "agent_communication"),
        ("Agent mesh communication", "agent_communication"),
        ("Broadcast to all agents", "agent_communication"),
        ("Dispatch handler for route", "agent_communication"),
    ]
    
    correct = 0
    results = []
    total_latency = 0
    
    for query, expected in test_cases:
        r = router.route(query)
        ok = r.route == expected
        if ok:
            correct += 1
        total_latency += r.latency_ms
        results.append({
            "query": query,
            "expected": expected,
            "got": r.route,
            "correct": ok,
            "confidence": round(r.confidence, 4),
            "method": r.method,
            "latency_ms": round(r.latency_ms, 2),
        })
    
    accuracy = correct / len(test_cases) * 100
    
    return JSONResponse({
        "accuracy": round(accuracy, 1),
        "correct": correct,
        "total": len(test_cases),
        "avg_latency_ms": round(total_latency / len(test_cases), 2),
        "failures": [r for r in results if not r["correct"]],
        "results": results,
    })


async def planner_endpoint(request):
    if not check_auth(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    body = await parse_json_body(request)
    if body is None:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    query = body.get("query", "")
    if not query:
        return JSONResponse({"error": "Missing 'query'"}, status_code=400)
    planner = ensure_planner()
    if planner is None:
        return JSONResponse({"error": "Planner unavailable", "detail": _planner_error}, status_code=503)
    top_k = body.get("top_k", SHADOW_TOP_K)
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid 'top_k'"}, status_code=400)
    plan = planner.plan(query, top_k=top_k)
    return JSONResponse(plan)

# ── App ──────────────────────────────────────────────────────
app = Starlette(routes=[
    Route("/health", health),
    Route("/route", route_message, methods=["POST"]),
    Route("/batch", batch_route, methods=["POST"]),
    Route("/plan", planner_endpoint, methods=["POST"]),
    Route("/stats", get_stats),
    Route("/routes", list_routes),
    Route("/benchmark", benchmark, methods=["POST"]),
])
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if __name__ == "__main__":
    ensure_initialized()
    log.info(f"🧭 Production Router V3 on http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
