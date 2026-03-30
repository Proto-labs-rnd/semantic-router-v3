#!/usr/bin/env python3
"""Shared Route Vocabulary — canonical route definitions for the semantic routing stack.

All routing components (Router V3 API, Query Router Integration, Prefilter)
import from this single source of truth to prevent silent drift.

Created: 2026-03-30
"""

from __future__ import annotations

# ── Canonical routes ──────────────────────────────────────────────────────────
# Must match ROUTE_CONCEPTS keys in message_router_v3_base.py
CANONICAL_ROUTES: list[str] = [
    "dev_request",
    "ops_request",
    "infrastructure_health",
    "security_alert",
    "experiment_request",
    "research_query",
    "monitoring",
    "agent_communication",
]

# ── Route → Agent mapping ────────────────────────────────────────────────────
ROUTE_AGENT_MAP: dict[str, str] = {
    "dev_request": "tachikoma",
    "ops_request": "orion",
    "infrastructure_health": "orion",
    "security_alert": "aegis",
    "experiment_request": "proto",
    "research_query": "specter",
    "monitoring": "orion",
    "agent_communication": "tachikoma",
}

DEFAULT_AGENT: str = "tachikoma"

# ── Route keyword hints (used by Query Router Integration) ───────────────────
ROUTE_HINTS: dict[str, list[str]] = {
    "monitoring": ["monitor", "monitoring", "metrics", "latency", "health", "stats", "dashboard", "alert"],
    "security_alert": ["security", "firewall", "vulnerability", "tls", "ssl", "auth", "harden"],
    "dev_request": ["code", "script", "api", "test", "debug", "feature", "implementation", "sync"],
    "ops_request": ["deploy", "restart", "install", "configure", "backup", "restore", "runbook", "service"],
    "research_query": ["research", "compare", "explain", "how", "architecture", "tradeoff", "guide", "documentation"],
    "experiment_request": ["experiment", "benchmark", "prototype", "poc", "evaluate", "validation", "sandbox", "context"],
    "infrastructure_health": ["cpu", "memory", "disk", "temperature", "network", "latency", "status", "capacity"],
    "agent_communication": ["route", "router", "message", "bus", "dispatch", "mesh", "agent"],
}


def agent_for(route: str) -> str:
    """Return the agent assigned to a route, falling back to DEFAULT_AGENT."""
    return ROUTE_AGENT_MAP.get(route, DEFAULT_AGENT)


def is_valid_route(route: str) -> bool:
    """Check if a route name is canonical."""
    return route in CANONICAL_ROUTES


def validate_route(route: str) -> str | None:
    """Return the canonical route if valid, else None.

    Also accepts 'unknown' as a special pseudo-route.
    """
    if route == "unknown":
        return route
    if route in CANONICAL_ROUTES:
        return route
    return None


def diff_against(route_agent_map: dict[str, str]) -> dict:
    """Compare an external route→agent map against the shared vocabulary.

    Returns {added, removed, changed, ok}.
    """
    shared_keys = set(ROUTE_AGENT_MAP.keys())
    ext_keys = set(route_agent_map.keys())
    added = ext_keys - shared_keys
    removed = shared_keys - ext_keys
    common = shared_keys & ext_keys
    changed = {k for k in common if ROUTE_AGENT_MAP[k] != route_agent_map[k]}
    ok = common - changed
    return {
        "added": sorted(added),
        "removed": sorted(removed),
        "changed": sorted(changed),
        "ok": sorted(ok),
    }


if __name__ == "__main__":
    import json
    print(json.dumps({
        "canonical_routes": CANONICAL_ROUTES,
        "route_agent_map": ROUTE_AGENT_MAP,
        "default_agent": DEFAULT_AGENT,
        "route_hint_counts": {k: len(v) for k, v in ROUTE_HINTS.items()},
    }, indent=2))
