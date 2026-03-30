#!/usr/bin/env python3
"""Aggregate Router V3 planner-shadow NDJSON logs into a small dashboard.

Inputs: NDJSON lines emitted by message-router-v3-api.py shadow mode.
Outputs: JSON summary, Markdown report, and optional review-corpus JSONL.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSON on line {line_no} of {path}: {exc}") from exc
        events.append(event)
    return events


def mean_or_zero(values: list[float]) -> float:
    return round(statistics.fmean(values), 2) if values else 0.0


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return round(sorted_values[0], 2)
    index = (len(sorted_values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = index - lower
    value = sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac
    return round(value, 2)


def top_tool(event: dict[str, Any]) -> dict[str, Any] | None:
    candidates = event.get("shadow", {}).get("tool_candidates") or []
    return candidates[0] if candidates else None


def summarize(events: list[dict[str, Any]], slow_ms: float) -> dict[str, Any]:
    planner_events = [event for event in events if event.get("mode", "shadow") != "prefilter_shadow"]
    prefilter_events = [event for event in events if event.get("mode") == "prefilter_shadow"]

    live_routes = Counter()
    planner_routes = Counter()
    actions = Counter()
    route_pairs = Counter()
    mismatch_pairs = Counter()
    top_tools = Counter()
    corrected_tools = Counter()
    note_counter = Counter()
    live_methods = Counter()

    live_latencies: list[float] = []
    shadow_latencies: list[float] = []
    corrected_examples: list[dict[str, Any]] = []
    clarify_examples: list[dict[str, Any]] = []
    slow_events: list[dict[str, Any]] = []

    corrected = 0
    matches = 0

    for event in planner_events:
        live = event.get("live", {})
        shadow = event.get("shadow", {})
        comparison = event.get("comparison", {})
        route_info = shadow.get("route", {})
        action = shadow.get("action", {})
        notes = route_info.get("notes") or []

        live_route = comparison.get("live_route") or live.get("route") or "unknown"
        planner_route = comparison.get("planner_route") or route_info.get("resolved") or "unknown"
        action_type = action.get("type") or "unknown"
        live_method = live.get("method") or "unknown"
        pair = f"{live_route}->{planner_route}"
        tt = top_tool(event)
        tt_name = tt.get("name") if tt else None

        live_routes[live_route] += 1
        planner_routes[planner_route] += 1
        actions[action_type] += 1
        route_pairs[pair] += 1
        live_methods[live_method] += 1

        for note in notes:
            note_counter[note] += 1

        if tt_name:
            top_tools[tt_name] += 1

        live_latency = float(live.get("latency_ms") or 0.0)
        shadow_latency = float(shadow.get("latency_ms") or 0.0)
        live_latencies.append(live_latency)
        shadow_latencies.append(shadow_latency)

        is_match = bool(comparison.get("match"))
        is_corrected = bool(comparison.get("corrected"))
        if is_match:
            matches += 1
        if is_corrected:
            corrected += 1
            mismatch_pairs[pair] += 1
            if tt_name and action_type == "execute_local":
                corrected_tools[tt_name] += 1
            corrected_examples.append(
                {
                    "query": event.get("query"),
                    "live_route": live_route,
                    "planner_route": planner_route,
                    "action": action_type,
                    "top_tool": tt_name,
                    "top_tool_score": round(float(tt.get("score") or 0.0), 4) if tt else None,
                    "live_latency_ms": round(live_latency, 2),
                    "shadow_latency_ms": round(shadow_latency, 2),
                    "notes": notes,
                }
            )

        if action_type == "clarify":
            clarify_examples.append(
                {
                    "query": event.get("query"),
                    "live_route": live_route,
                    "planner_route": planner_route,
                    "top_tool": tt_name,
                    "top_tool_score": round(float(tt.get("score") or 0.0), 4) if tt else None,
                    "reason": action.get("reason"),
                }
            )

        if live_latency >= slow_ms or shadow_latency >= slow_ms:
            slow_events.append(
                {
                    "query": event.get("query"),
                    "live_route": live_route,
                    "planner_route": planner_route,
                    "live_latency_ms": round(live_latency, 2),
                    "shadow_latency_ms": round(shadow_latency, 2),
                    "action": action_type,
                }
            )

    live_latencies_sorted = sorted(live_latencies)
    shadow_latencies_sorted = sorted(shadow_latencies)
    planner_total = len(planner_events)
    mismatch_count = planner_total - matches

    corrected_examples.sort(
        key=lambda item: (item["shadow_latency_ms"], item["top_tool_score"] or 0.0), reverse=True
    )
    clarify_examples.sort(key=lambda item: item["top_tool_score"] or 0.0, reverse=True)
    slow_events.sort(key=lambda item: max(item["live_latency_ms"], item["shadow_latency_ms"]), reverse=True)

    pf_rules = Counter()
    pf_route_pairs = Counter()
    pf_corrected_examples: list[dict[str, Any]] = []
    pf_live_latencies: list[float] = []
    pf_shadow_latencies: list[float] = []
    pf_matches = 0

    for event in prefilter_events:
        live = event.get("live", {})
        prefilter = event.get("prefilter", {})
        comparison = event.get("comparison", {})
        live_route = comparison.get("live_route") or live.get("route") or "unknown"
        final_route = comparison.get("prefilter_route") or prefilter.get("final_route") or live_route
        rule = prefilter.get("rule") or "unknown"
        detail = prefilter.get("detail") or ""
        pair = f"{live_route}->{final_route}"
        live_latency = float(live.get("latency_ms") or 0.0)
        shadow_latency = float(prefilter.get("latency_ms") or 0.0)

        pf_rules[rule] += 1
        pf_route_pairs[pair] += 1
        pf_live_latencies.append(live_latency)
        pf_shadow_latencies.append(shadow_latency)
        if comparison.get("match"):
            pf_matches += 1
        if comparison.get("corrected"):
            pf_corrected_examples.append(
                {
                    "query": event.get("query"),
                    "live_route": live_route,
                    "prefilter_route": final_route,
                    "rule": rule,
                    "detail": detail,
                    "live_latency_ms": round(live_latency, 2),
                    "shadow_latency_ms": round(shadow_latency, 2),
                }
            )

    pf_live_sorted = sorted(pf_live_latencies)
    pf_shadow_sorted = sorted(pf_shadow_latencies)
    pf_total = len(prefilter_events)
    pf_corrected_examples.sort(key=lambda item: item["shadow_latency_ms"], reverse=True)

    summary = {
        "source": {
            "events": len(events),
            "planner_events": planner_total,
            "prefilter_events": pf_total,
        },
        "overview": {
            "total": planner_total,
            "matches": matches,
            "mismatches": mismatch_count,
            "corrected": corrected,
            "match_rate": round((matches / planner_total) * 100, 1) if planner_total else 0.0,
            "correction_rate": round((corrected / planner_total) * 100, 1) if planner_total else 0.0,
        },
        "latency_ms": {
            "live_avg": mean_or_zero(live_latencies),
            "live_p50": percentile(live_latencies_sorted, 0.50),
            "live_p95": percentile(live_latencies_sorted, 0.95),
            "live_max": round(max(live_latencies, default=0.0), 2),
            "shadow_avg": mean_or_zero(shadow_latencies),
            "shadow_p50": percentile(shadow_latencies_sorted, 0.50),
            "shadow_p95": percentile(shadow_latencies_sorted, 0.95),
            "shadow_max": round(max(shadow_latencies, default=0.0), 2),
        },
        "distributions": {
            "live_routes": dict(live_routes.most_common()),
            "planner_routes": dict(planner_routes.most_common()),
            "live_methods": dict(live_methods.most_common()),
            "actions": dict(actions.most_common()),
            "top_tools": dict(top_tools.most_common(10)),
            "corrected_tools": dict(corrected_tools.most_common(10)),
            "notes": dict(note_counter.most_common()),
        },
        "route_pairs": {
            "all": [{"pair": pair, "count": count} for pair, count in route_pairs.most_common()],
            "mismatches": [
                {"pair": pair, "count": count}
                for pair, count in mismatch_pairs.most_common()
            ],
        },
        "examples": {
            "corrected": corrected_examples[:10],
            "clarify": clarify_examples[:10],
            "slow": slow_events[:10],
        },
        "prefilter_shadow": {
            "total": pf_total,
            "matches": pf_matches,
            "mismatches": pf_total - pf_matches,
            "match_rate": round((pf_matches / pf_total) * 100, 1) if pf_total else 0.0,
            "rules": dict(pf_rules.most_common()),
            "route_pairs": [{"pair": pair, "count": count} for pair, count in pf_route_pairs.most_common()],
            "latency_ms": {
                "live_avg": mean_or_zero(pf_live_latencies),
                "live_p50": percentile(pf_live_sorted, 0.50),
                "live_p95": percentile(pf_live_sorted, 0.95),
                "live_max": round(max(pf_live_latencies, default=0.0), 2),
                "shadow_avg": mean_or_zero(pf_shadow_latencies),
                "shadow_p50": percentile(pf_shadow_sorted, 0.50),
                "shadow_p95": percentile(pf_shadow_sorted, 0.95),
                "shadow_max": round(max(pf_shadow_latencies, default=0.0), 2),
            },
            "examples": {
                "corrected": pf_corrected_examples[:10],
            },
        },
    }
    return summary


def build_review_rows(events: list[dict[str, Any]], only_mismatch: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, event in enumerate(events, start=1):
        if event.get("mode") == "prefilter_shadow":
            continue
        comparison = event.get("comparison", {})
        if only_mismatch and comparison.get("match"):
            continue

        live = event.get("live", {})
        shadow = event.get("shadow", {})
        route_info = shadow.get("route", {})
        action = shadow.get("action", {})
        tt = top_tool(event)

        rows.append(
            {
                "id": f"drift-{idx:03d}",
                "query": event.get("query"),
                "live_route": comparison.get("live_route") or live.get("route"),
                "planner_route": comparison.get("planner_route") or route_info.get("resolved"),
                "match": bool(comparison.get("match")),
                "corrected": bool(comparison.get("corrected")),
                "live_agent": live.get("agent"),
                "planner_agent": shadow.get("agent"),
                "action_type": action.get("type"),
                "action_reason": action.get("reason"),
                "top_tool": tt.get("name") if tt else None,
                "top_tool_score": round(float(tt.get("score") or 0.0), 4) if tt else None,
                "notes": route_info.get("notes") or [],
                "expected_route": "",
                "planner_helpful": "",
                "reviewer_notes": "",
            }
        )
    return rows


def to_markdown(summary: dict[str, Any], source_path: Path) -> str:
    ov = summary["overview"]
    lat = summary["latency_ms"]
    dist = summary["distributions"]
    pairs = summary["route_pairs"]
    examples = summary["examples"]

    lines = [
        f"# Router Shadow Dashboard — {source_path.name}",
        "",
        "## Overview",
        f"- Total events: {ov['total']}",
        f"- Matches: {ov['matches']} ({ov['match_rate']}%)",
        f"- Mismatches: {ov['mismatches']}",
        f"- Corrections: {ov['corrected']} ({ov['correction_rate']}%)",
        "",
        "## Latency (ms)",
        f"- Live: avg {lat['live_avg']} | p50 {lat['live_p50']} | p95 {lat['live_p95']} | max {lat['live_max']}",
        f"- Shadow: avg {lat['shadow_avg']} | p50 {lat['shadow_p50']} | p95 {lat['shadow_p95']} | max {lat['shadow_max']}",
        "",
        "## Action distribution",
    ]
    for action, count in dist["actions"].items():
        lines.append(f"- {action}: {count}")

    lines.extend(["", "## Top mismatch route pairs"])
    if pairs["mismatches"]:
        for item in pairs["mismatches"][:10]:
            lines.append(f"- {item['pair']}: {item['count']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Top corrected-tool signals"])
    corrected_tools = dist.get("corrected_tools", {})
    if corrected_tools:
        for tool, count in list(corrected_tools.items())[:10]:
            lines.append(f"- {tool}: {count}")
    else:
        lines.append("- none")

    pf = summary.get("prefilter_shadow", {})
    if pf.get("total"):
        pf_lat = pf.get("latency_ms", {})
        lines.extend(["", "## Prefilter shadow"])
        lines.append(f"- Total events: {pf['total']}")
        lines.append(f"- Matches: {pf['matches']} ({pf['match_rate']}%)")
        lines.append(f"- Mismatches: {pf['mismatches']}")
        lines.append(
            f"- Latency: live avg {pf_lat.get('live_avg', 0.0)} | prefilter avg {pf_lat.get('shadow_avg', 0.0)} | p95 {pf_lat.get('shadow_p95', 0.0)}"
        )
        lines.append("")
        lines.append("### Rules")
        rules = pf.get("rules", {})
        if rules:
            for rule, count in list(rules.items())[:10]:
                lines.append(f"- {rule}: {count}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("### Corrected examples")
        pf_examples = pf.get("examples", {}).get("corrected", [])
        if pf_examples:
            for item in pf_examples[:8]:
                detail_suffix = f" | detail: {item['detail']}" if item.get("detail") else ""
                lines.append(
                    f"- `{item['query']}` → {item['live_route']} → {item['prefilter_route']} | rule: {item['rule']}{detail_suffix}"
                )
        else:
            lines.append("- none")

    lines.extend(["", "## Corrected examples"])
    if examples["corrected"]:
        for item in examples["corrected"][:8]:
            note_suffix = f" | notes: {', '.join(item['notes'])}" if item["notes"] else ""
            tool_suffix = f" | tool: {item['top_tool']} ({item['top_tool_score']})" if item["top_tool"] else ""
            lines.append(
                f"- `{item['query']}` → {item['live_route']} → {item['planner_route']} | action: {item['action']}{tool_suffix}{note_suffix}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Clarify examples"])
    if examples["clarify"]:
        for item in examples["clarify"][:8]:
            tool_suffix = f" | top tool: {item['top_tool']} ({item['top_tool_score']})" if item["top_tool"] else ""
            lines.append(
                f"- `{item['query']}` | route: {item['live_route']} | planner: {item['planner_route']} | reason: {item['reason']}{tool_suffix}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Slow cases"])
    if examples["slow"]:
        for item in examples["slow"][:8]:
            lines.append(
                f"- `{item['query']}` | live {item['live_latency_ms']} ms | shadow {item['shadow_latency_ms']} ms | {item['live_route']} -> {item['planner_route']} | action: {item['action']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Notes signals"])
    notes = dist.get("notes", {})
    if notes:
        for note, count in list(notes.items())[:10]:
            lines.append(f"- {count}× {note}")
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="Path to planner shadow NDJSON log")
    parser.add_argument("--output-json", help="Write JSON summary to this path")
    parser.add_argument("--output-md", help="Write Markdown report to this path")
    parser.add_argument("--review-jsonl", help="Write review seed JSONL to this path")
    parser.add_argument("--include-matches-in-review", action="store_true", help="Include matches in review seed export")
    parser.add_argument("--slow-ms", type=float, default=500.0, help="Latency threshold for slow-case section")
    args = parser.parse_args()

    log_path = Path(args.log)
    events = load_events(log_path)
    summary = summarize(events, slow_ms=args.slow_ms)

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    if args.output_md:
        out = Path(args.output_md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_markdown(summary, log_path))

    if args.review_jsonl:
        rows = build_review_rows(events, only_mismatch=not args.include_matches_in_review)
        out = Path(args.review_jsonl)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
