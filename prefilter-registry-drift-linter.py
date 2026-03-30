#!/usr/bin/env python3
"""Audit the shared meta-routing prefilter registry for drift and rule interactions.

This tool is intentionally read-only. It validates the registry, optionally replays
an evaluation corpus, and surfaces evidence for:
- static registry drift (missing targets, invalid routes, duplicate rule names)
- unused term sets / signals
- dead rules and rules that never win on a replay corpus
- collision rows where multiple rules match the same query
- order-sensitive route conflicts where rule priority changes the outcome
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Iterable

from meta_routing_prefilter import (
    SIGNAL_BUILDERS,
    apply_rule,
    build_signals,
    get_registry,
    normalize,
    registry_stats,
)

VALID_ROUTES = {
    "agent_communication",
    "dev_request",
    "experiment_request",
    "infrastructure_health",
    "monitoring",
    "ops_request",
    "research_query",
}

SIGNAL_TERM_SETS = {
    "explicit_tool_verb_prefix": {"explicit_tool_verbs"},
    "testing_execution_prefix": {"testing_execution_prefixes"},
    "testing_pattern": {"testing_patterns"},
    "repair_verb": {"repair_verbs"},
    "ops_verb": {"ops_verbs"},
    "context_guard": {"context_guard_patterns"},
    "health_check": {"health_check_patterns"},
    "research_pattern": {"research_patterns"},
    "question_prefix": {"question_research_prefixes"},
    "meta_experiment": {"meta_experiment_patterns"},
    "meta_monitoring": {"meta_monitoring_patterns"},
    "meta_agent": {"meta_agent_patterns"},
    "metric_term": {"metric_terms"},
    "health_term": {"health_terms"},
    "service_term": {"service_terms"},
}


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows



def pct(part: int, whole: int) -> float:
    if whole == 0:
        return 0.0
    return round((part / whole) * 100.0, 1)



def count_duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)



def referenced_term_sets(registry: dict) -> set[str]:
    referenced: set[str] = set()
    for rule in registry["rules"]:
        if rule.get("literal_set"):
            referenced.add(rule["literal_set"])
        for key in ("signal", "prefix_signal", "pattern_signal"):
            signal_name = rule.get(key)
            if signal_name:
                referenced.update(SIGNAL_TERM_SETS.get(signal_name, set()))
        for signal_name in rule.get("signals", []):
            referenced.update(SIGNAL_TERM_SETS.get(signal_name, set()))
    return referenced



def referenced_signals(registry: dict) -> set[str]:
    used: set[str] = set()
    for rule in registry["rules"]:
        for key in ("signal", "prefix_signal", "pattern_signal"):
            signal_name = rule.get(key)
            if signal_name:
                used.add(signal_name)
        used.update(rule.get("signals", []))
    return used



def audit_static(registry: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    tool_route_map = registry["tool_route_map"]
    tool_aliases = registry["tool_aliases"]
    term_sets = registry["term_sets"]
    rules = registry["rules"]

    duplicate_rule_names = count_duplicates(rule["name"] for rule in rules)
    if duplicate_rule_names:
        errors.append(f"Duplicate rule names: {duplicate_rule_names}")

    invalid_tool_routes = {
        tool: route
        for tool, route in tool_route_map.items()
        if route not in VALID_ROUTES
    }
    if invalid_tool_routes:
        errors.append(f"Tool routes reference unknown routes: {invalid_tool_routes}")

    bad_alias_targets = {
        alias: target
        for alias, target in tool_aliases.items()
        if target not in tool_route_map
    }
    if bad_alias_targets:
        errors.append(f"Tool aliases reference missing tools: {bad_alias_targets}")

    invalid_rule_routes = {
        rule["name"]: rule["route"]
        for rule in rules
        if rule.get("route") not in (None, "tool_route") and rule["route"] not in VALID_ROUTES
    }
    if invalid_rule_routes:
        errors.append(f"Rules reference unknown routes: {invalid_rule_routes}")

    duplicated_term_values = {
        name: duplicates
        for name, values in term_sets.items()
        if (duplicates := count_duplicates(values))
    }
    if duplicated_term_values:
        warnings.append(f"Term sets contain duplicate values: {duplicated_term_values}")

    used_term_sets = referenced_term_sets(registry)
    unused_term_sets = sorted(set(term_sets) - used_term_sets)
    if unused_term_sets:
        warnings.append(f"Unused term sets: {unused_term_sets}")

    used_signals = referenced_signals(registry)
    unused_signals = sorted(set(SIGNAL_BUILDERS) - used_signals)
    if unused_signals:
        warnings.append(f"Unused signals: {unused_signals}")

    return {
        "errors": errors,
        "warnings": warnings,
        "valid_routes": sorted(VALID_ROUTES),
        "used_term_sets": sorted(used_term_sets),
        "unused_term_sets": unused_term_sets,
        "used_signals": sorted(used_signals),
        "unused_signals": unused_signals,
    }



def matched_rules_for_row(registry: dict, row: dict) -> dict:
    query = normalize(row.get("query", ""))
    tool_name = None
    if query:
        # build_signals needs the same tool detection path as runtime.
        from meta_routing_prefilter import find_tool  # local import keeps CLI dependency small

        tool_name = find_tool(query)
    signals = build_signals(query, tool_name)

    matches = []
    for rule in registry["rules"]:
        decision = apply_rule(rule, query, tool_name, signals)
        if decision:
            matches.append(
                {
                    "rule": decision.rule,
                    "route": decision.route,
                    "detail": decision.detail,
                }
            )

    winner = matches[0] if matches else None
    return {
        "query": query,
        "tool_name": tool_name,
        "signals": {name: detail for name, detail in signals.items() if detail},
        "matches": matches,
        "winner": winner,
    }



def audit_corpus(registry: dict, rows: list[dict]) -> dict:
    winner_hits = Counter()
    match_hits = Counter()
    shadow_hits = Counter()
    collision_pairs = Counter()
    route_conflict_pairs = Counter()
    collision_examples = []
    route_conflict_examples = []
    no_match_rows = 0
    collision_rows = 0
    route_conflict_rows = 0

    for row in rows:
        result = matched_rules_for_row(registry, row)
        matches = result["matches"]
        winner = result["winner"]

        if winner:
            winner_hits[winner["rule"]] += 1
        else:
            no_match_rows += 1

        for match in matches:
            match_hits[match["rule"]] += 1
        for match in matches[1:]:
            shadow_hits[match["rule"]] += 1

        if len(matches) > 1:
            collision_rows += 1
            pair_names = [match["rule"] for match in matches]
            for left, right in combinations(pair_names, 2):
                collision_pairs[f"{left} -> {right}"] += 1
            if len(collision_examples) < 10:
                collision_examples.append(
                    {
                        "id": row.get("id"),
                        "query": row.get("query"),
                        "winner": winner,
                        "matches": matches,
                    }
                )

            routes = [match["route"] for match in matches if match["route"] is not None]
            unique_routes = set(routes)
            if len(unique_routes) > 1:
                route_conflict_rows += 1
                for left, right in combinations(matches, 2):
                    if left["route"] != right["route"]:
                        route_conflict_pairs[f"{left['rule']}:{left['route']} -> {right['rule']}:{right['route']}"] += 1
                if len(route_conflict_examples) < 10:
                    route_conflict_examples.append(
                        {
                            "id": row.get("id"),
                            "query": row.get("query"),
                            "winner": winner,
                            "signals": result["signals"],
                            "matches": matches,
                        }
                    )

    rule_names = [rule["name"] for rule in registry["rules"]]
    dead_rules = [name for name in rule_names if match_hits[name] == 0]
    never_win_rules = [name for name in rule_names if winner_hits[name] == 0]

    return {
        "rows": len(rows),
        "no_match_rows": no_match_rows,
        "no_match_rate": pct(no_match_rows, len(rows)),
        "collision_rows": collision_rows,
        "collision_rate": pct(collision_rows, len(rows)),
        "route_conflict_rows": route_conflict_rows,
        "route_conflict_rate": pct(route_conflict_rows, len(rows)),
        "winner_hits": dict(winner_hits.most_common()),
        "match_hits": dict(match_hits.most_common()),
        "shadow_hits": dict(shadow_hits.most_common()),
        "dead_rules": dead_rules,
        "never_win_rules": never_win_rules,
        "collision_pairs": dict(collision_pairs.most_common(12)),
        "route_conflict_pairs": dict(route_conflict_pairs.most_common(12)),
        "examples": {
            "collisions": collision_examples,
            "route_conflicts": route_conflict_examples,
        },
    }



def to_markdown(report: dict) -> str:
    static = report["static"]
    lines = [
        "# Prefilter Registry Drift Linter",
        "",
        "## Registry",
        "",
        f"- Rules: **{report['registry']['rules']}**",
        f"- Term sets: **{report['registry']['term_sets']}**",
        f"- Tool routes: **{report['registry']['tools']}**",
        f"- Tool aliases: **{report['registry']['aliases']}**",
        "",
        "## Static checks",
        "",
    ]

    if static["errors"]:
        lines.append("### Errors")
        lines.append("")
        for item in static["errors"]:
            lines.append(f"- {item}")
        lines.append("")
    else:
        lines.extend(["- No static errors detected", ""])

    if static["warnings"]:
        lines.append("### Warnings")
        lines.append("")
        for item in static["warnings"]:
            lines.append(f"- {item}")
        lines.append("")

    corpus = report.get("corpus")
    if corpus:
        lines.extend(
            [
                "## Corpus replay audit",
                "",
                f"- Rows: **{corpus['rows']}**",
                f"- No-match rows: **{corpus['no_match_rows']}** ({corpus['no_match_rate']}%)",
                f"- Collision rows: **{corpus['collision_rows']}** ({corpus['collision_rate']}%)",
                f"- Route-conflict rows: **{corpus['route_conflict_rows']}** ({corpus['route_conflict_rate']}%)",
                "",
                "### Dead / never-win rules",
                "",
                f"- Dead rules: `{', '.join(corpus['dead_rules']) or 'none'}`",
                f"- Never-win rules: `{', '.join(corpus['never_win_rules']) or 'none'}`",
                "",
                "### Winner hit counts",
                "",
            ]
        )
        for name, count in corpus["winner_hits"].items():
            lines.append(f"- `{name}`: {count}")
        lines.extend(["", "### Route-conflict examples", ""])
        for example in corpus["examples"]["route_conflicts"][:8]:
            rendered = ", ".join(f"`{item['rule']}`→`{item['route']}`" for item in example["matches"])
            lines.append(f"- `{example['id']}` | {rendered} | {example['query']}")

    return "\n".join(lines) + "\n"



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", nargs="?", help="Optional labeled corpus JSONL to replay")
    parser.add_argument("--output-json", help="Write JSON report to this path")
    parser.add_argument("--output-md", help="Write Markdown report to this path")
    args = parser.parse_args()

    registry = get_registry()
    report = {
        "registry": registry_stats(),
        "static": audit_static(registry),
    }

    if args.corpus:
        rows = load_jsonl(Path(args.corpus))
        report["corpus"] = audit_corpus(registry, rows)

    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)

    if args.output_json:
        Path(args.output_json).write_text(rendered + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(to_markdown(report), encoding="utf-8")

    return 1 if report["static"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
