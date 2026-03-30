from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

# Runtime and offline evaluation share the same deterministic registry.

REGISTRY_PATH = Path(__file__).with_name("meta_routing_prefilter_rules.json")
KNOWN_RULE_KINDS = {
    "all_signals",
    "literal",
    "literal_and_signal",
    "literal_set_and_signal",
    "prefix_and_pattern",
    "signal",
    "signal_and_literals",
    "tool_and_prefix",
    "tool_lookup",
}


@dataclass
class Decision:
    route: str | None
    rule: str
    detail: str


@lru_cache(maxsize=1)
def load_registry() -> dict:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    validate_registry(registry)
    return registry


def validate_registry(registry: dict) -> None:
    required_top_level = {"tool_route_map", "tool_aliases", "term_sets", "rules"}
    missing = required_top_level - set(registry)
    if missing:
        raise ValueError(f"Prefilter registry missing keys: {sorted(missing)}")

    term_sets = registry["term_sets"]
    if not isinstance(term_sets, dict):
        raise ValueError("Prefilter registry term_sets must be a mapping")

    for index, rule in enumerate(registry["rules"]):
        kind = rule.get("kind")
        name = rule.get("name")
        if not name:
            raise ValueError(f"Prefilter rule #{index} missing name")
        if kind not in KNOWN_RULE_KINDS:
            raise ValueError(f"Prefilter rule {name!r} has unknown kind {kind!r}")

        for key in ("signal", "prefix_signal", "pattern_signal"):
            value = rule.get(key)
            if value and value not in SIGNAL_BUILDERS:
                raise ValueError(f"Prefilter rule {name!r} references unknown signal {value!r}")

        for value in rule.get("signals", []):
            if value not in SIGNAL_BUILDERS:
                raise ValueError(f"Prefilter rule {name!r} references unknown signal {value!r}")

        literal_set = rule.get("literal_set")
        if literal_set and literal_set not in term_sets:
            raise ValueError(f"Prefilter rule {name!r} references missing term set {literal_set!r}")


def get_registry() -> dict:
    return load_registry()


def registry_stats() -> dict:
    registry = load_registry()
    return {
        "rules": len(registry["rules"]),
        "term_sets": len(registry["term_sets"]),
        "tools": len(registry["tool_route_map"]),
        "aliases": len(registry["tool_aliases"]),
    }


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def term_set(name: str) -> tuple[str, ...]:
    return tuple(load_registry()["term_sets"].get(name, ()))


def tool_route_map() -> dict[str, str]:
    return dict(load_registry()["tool_route_map"])


def tool_aliases() -> dict[str, str]:
    return dict(load_registry()["tool_aliases"])


def find_tool(query: str) -> str | None:
    text = normalize(query)
    for tool_name in load_registry()["tool_route_map"]:
        if tool_name.lower() in text:
            return tool_name
    for alias, tool_name in load_registry()["tool_aliases"].items():
        if alias in text:
            return tool_name
    return None


def contains_any(text: str, terms: Iterable[str]) -> str | None:
    for term in terms:
        if term in text:
            return term
    return None


def starts_with_any(text: str, terms: Iterable[str]) -> str | None:
    for term in terms:
        if text.startswith(term):
            return term
    return None


def _signal_explicit_tool_verb_prefix(query: str, tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    return starts_with_any(query, term_set("explicit_tool_verbs"))


def _signal_testing_execution_prefix(query: str, tool_name: str | None) -> str | None:
    return starts_with_any(query, term_set("testing_execution_prefixes"))


def _signal_testing_pattern(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("testing_patterns"))


def _signal_repair_verb(query: str, tool_name: str | None) -> str | None:
    return starts_with_any(query, term_set("repair_verbs"))


def _signal_ops_verb(query: str, tool_name: str | None) -> str | None:
    return starts_with_any(query, term_set("ops_verbs"))


def _signal_context_guard(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("context_guard_patterns"))


def _signal_health_check(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("health_check_patterns"))


def _signal_research_pattern(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("research_patterns"))


def _signal_question_prefix(query: str, tool_name: str | None) -> str | None:
    return starts_with_any(query, term_set("question_research_prefixes"))


def _signal_meta_experiment(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("meta_experiment_patterns"))


def _signal_meta_monitoring(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("meta_monitoring_patterns"))


def _signal_meta_agent(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("meta_agent_patterns"))


def _signal_metric_term(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("metric_terms"))


def _signal_health_term(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("health_terms"))


def _signal_service_term(query: str, tool_name: str | None) -> str | None:
    return contains_any(query, term_set("service_terms"))


SIGNAL_BUILDERS = {
    "explicit_tool_verb_prefix": _signal_explicit_tool_verb_prefix,
    "testing_execution_prefix": _signal_testing_execution_prefix,
    "testing_pattern": _signal_testing_pattern,
    "repair_verb": _signal_repair_verb,
    "ops_verb": _signal_ops_verb,
    "context_guard": _signal_context_guard,
    "health_check": _signal_health_check,
    "research_pattern": _signal_research_pattern,
    "question_prefix": _signal_question_prefix,
    "meta_experiment": _signal_meta_experiment,
    "meta_monitoring": _signal_meta_monitoring,
    "meta_agent": _signal_meta_agent,
    "metric_term": _signal_metric_term,
    "health_term": _signal_health_term,
    "service_term": _signal_service_term,
}


def build_signals(query: str, tool_name: str | None) -> dict[str, str | None]:
    return {
        name: builder(query, tool_name)
        for name, builder in SIGNAL_BUILDERS.items()
    }


def resolve_route(rule: dict, tool_name: str | None) -> str | None:
    route = rule.get("route")
    if route != "tool_route":
        return route
    if not tool_name:
        return None
    return load_registry()["tool_route_map"].get(tool_name)


def apply_rule(rule: dict, query: str, tool_name: str | None, signals: dict[str, str | None]) -> Decision | None:
    kind = rule["kind"]
    name = rule["name"]

    if kind == "tool_and_prefix":
        prefix = signals.get(rule["prefix_signal"])
        if tool_name and prefix:
            route = resolve_route(rule, tool_name)
            if route:
                return Decision(route, name, f"{prefix} + {tool_name}")
        return None

    if kind == "prefix_and_pattern":
        prefix = signals.get(rule["prefix_signal"])
        pattern = signals.get(rule["pattern_signal"])
        if prefix and pattern:
            return Decision(resolve_route(rule, tool_name), name, f"{prefix} + {pattern}")
        return None

    if kind == "signal":
        detail = signals.get(rule["signal"])
        if detail:
            return Decision(resolve_route(rule, tool_name), name, detail)
        return None

    if kind == "literal":
        literal = rule["literal"]
        if literal in query:
            return Decision(resolve_route(rule, tool_name), name, rule.get("detail", literal))
        return None

    if kind == "signal_and_literals":
        detail = signals.get(rule["signal"])
        required_literals = rule.get("require_any_literals", [])
        if detail and any(literal in query for literal in required_literals):
            return Decision(resolve_route(rule, tool_name), name, detail)
        return None

    if kind == "tool_lookup":
        if tool_name:
            route = resolve_route(rule, tool_name)
            if route:
                return Decision(route, name, tool_name)
        return None

    if kind == "literal_and_signal":
        literal = rule["literal"]
        detail = signals.get(rule["signal"])
        if literal in query and detail:
            return Decision(resolve_route(rule, tool_name), name, detail)
        return None

    if kind == "all_signals":
        details = [signals.get(signal_name) for signal_name in rule.get("signals", [])]
        if all(details):
            return Decision(resolve_route(rule, tool_name), name, " + ".join(detail for detail in details if detail))
        return None

    if kind == "literal_set_and_signal":
        detail = signals.get(rule["signal"])
        literal = contains_any(query, term_set(rule["literal_set"]))
        if literal and detail:
            return Decision(resolve_route(rule, tool_name), name, detail)
        return None

    raise ValueError(f"Unsupported prefilter rule kind: {kind}")


def decide_prefilter(row: dict) -> Decision:
    query = normalize(row.get("query", ""))
    tool_name = find_tool(query)
    signals = build_signals(query, tool_name)

    for rule in load_registry()["rules"]:
        decision = apply_rule(rule, query, tool_name, signals)
        if decision:
            return decision

    return Decision(None, "no_prefilter_match", "")
