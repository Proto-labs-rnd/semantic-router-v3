#!/usr/bin/env python3
"""Evaluate lightweight route-prefilter heuristics against a labeled corpus.

The prefilter is intentionally simple and deterministic:
- no embeddings
- no LLM calls
- only substring / regex checks and a tiny static tool map

It is meant to answer: can a lightweight pre-router fix the most expensive
router/planner drift classes before the heavier planner runs?
"""

from __future__ import annotations


import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from meta_routing_prefilter import decide_prefilter, registry_stats


def load_jsonl(path: Path) -> list[dict]:
    rows = []
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



def summarize(rows: list[dict]) -> dict:
    evaluated = []
    rule_counts = Counter()
    route_counts = Counter()
    family_counts = defaultdict(lambda: Counter())
    changed = 0
    decisive_total = 0
    decisive_correct = 0
    full_correct = 0
    observed_total = 0
    observed_correct = 0
    clarify_candidates = 0
    clarify_escaped = 0

    for row in rows:
        decision = decide_prefilter(row)
        expected = row.get("expected_route")
        live = row.get("live_route")
        source = row.get("source", "unknown")
        family = row.get("family", "unknown")
        label = row.get("label", "")
        clarify_legitimate = bool(row.get("clarify_legitimate"))

        final_route = decision.route or live
        prefilter_changed = final_route != live
        correct = bool(expected) and final_route == expected
        decisive = label != "ambiguous"

        if prefilter_changed:
            changed += 1
        if correct:
            full_correct += 1
        if decisive:
            decisive_total += 1
            if correct:
                decisive_correct += 1
        if source == "observed":
            observed_total += 1
            if correct:
                observed_correct += 1
        if clarify_legitimate and expected:
            clarify_candidates += 1
            if correct:
                clarify_escaped += 1

        rule_counts[decision.rule] += 1
        route_counts[final_route] += 1
        family_counts[family]["total"] += 1
        if correct:
            family_counts[family]["correct"] += 1
        if prefilter_changed:
            family_counts[family]["changed"] += 1

        evaluated.append(
            {
                **row,
                "prefilter_rule": decision.rule,
                "prefilter_detail": decision.detail,
                "prefilter_route": decision.route,
                "final_route": final_route,
                "prefilter_changed": prefilter_changed,
                "prefilter_correct": correct,
                "prefilter_decisive": decisive,
            }
        )

    family_summary = []
    for family, counters in sorted(family_counts.items()):
        total = counters["total"]
        family_summary.append(
            {
                "family": family,
                "count": total,
                "accuracy": pct(counters["correct"], total),
                "changed": counters["changed"],
                "changed_rate": pct(counters["changed"], total),
            }
        )

    summary = {
        "registry": registry_stats(),
        "corpus": {
            "total": len(rows),
            "observed": sum(1 for row in rows if row.get("source") == "observed"),
            "synthetic": sum(1 for row in rows if row.get("source") == "synthetic"),
        },
        "metrics": {
            "prefilter_deflection_rate": pct(changed, len(rows)),
            "prefilter_alignment_full": pct(full_correct, len(rows)),
            "prefilter_alignment_decisive": pct(decisive_correct, decisive_total),
            "prefilter_alignment_observed": pct(observed_correct, observed_total),
            "clarify_escape_rate": pct(clarify_escaped, clarify_candidates),
            "clarify_escape_candidates": clarify_candidates,
        },
        "rules": dict(rule_counts.most_common()),
        "final_routes": dict(route_counts.most_common()),
        "families": family_summary,
        "examples": {
            "changed_correct": [
                {
                    "id": row.get("id"),
                    "query": row.get("query"),
                    "live_route": row.get("live_route"),
                    "prefilter_route": row.get("prefilter_route"),
                    "final_route": row.get("final_route"),
                    "expected_route": row.get("expected_route"),
                    "prefilter_rule": row.get("prefilter_rule"),
                }
                for row in evaluated
                if row["prefilter_changed"] and row["prefilter_correct"]
            ][:12],
            "still_wrong": [
                {
                    "id": row.get("id"),
                    "query": row.get("query"),
                    "live_route": row.get("live_route"),
                    "prefilter_route": row.get("prefilter_route"),
                    "final_route": row.get("final_route"),
                    "expected_route": row.get("expected_route"),
                    "prefilter_rule": row.get("prefilter_rule"),
                }
                for row in evaluated
                if not row["prefilter_correct"]
            ][:12],
        },
        "evaluated_rows": evaluated,
    }
    return summary



def to_markdown(summary: dict) -> str:
    metrics = summary["metrics"]
    families = summary["families"]
    rules = summary["rules"]
    registry = summary["registry"]
    changed_correct = summary["examples"]["changed_correct"]
    still_wrong = summary["examples"]["still_wrong"]

    lines = [
        "# Meta-Routing Prefilter Evaluation",
        "",
        "## Registry",
        "",
        f"- Rules: **{registry['rules']}**",
        f"- Term sets: **{registry['term_sets']}**",
        f"- Tool routes: **{registry['tools']}**",
        f"- Tool aliases: **{registry['aliases']}**",
        "",
        "## Metrics",
        "",
        f"- Prefilter deflection rate: **{metrics['prefilter_deflection_rate']}%**",
        f"- Prefilter alignment (full): **{metrics['prefilter_alignment_full']}%**",
        f"- Prefilter alignment (decisive): **{metrics['prefilter_alignment_decisive']}%**",
        f"- Prefilter alignment (observed): **{metrics['prefilter_alignment_observed']}%**",
        f"- Clarify escape rate: **{metrics['clarify_escape_rate']}%** ({metrics['clarify_escape_candidates']} candidates)",
        "",
        "## Rule hit counts",
        "",
    ]

    for rule, count in rules.items():
        lines.append(f"- `{rule}`: {count}")

    lines.extend(["", "## Family accuracy", ""])
    for item in families:
        lines.append(
            f"- `{item['family']}`: accuracy {item['accuracy']}%, changed {item['changed']}/{item['count']} ({item['changed_rate']}%)"
        )

    lines.extend(["", "## Changed + correct examples", ""])
    for item in changed_correct[:8]:
        lines.append(
            f"- `{item['id']}` — `{item['live_route']}` → `{item['final_route']}` via `{item['prefilter_rule']}` | {item['query']}"
        )

    lines.extend(["", "## Still wrong / unresolved", ""])
    for item in still_wrong[:8]:
        lines.append(
            f"- `{item['id']}` — expected `{item['expected_route']}`, got `{item['final_route']}` via `{item['prefilter_rule']}` | {item['query']}"
        )

    return "\n".join(lines) + "\n"



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", help="Path to labeled corpus JSONL")
    parser.add_argument("--output-json", help="Write JSON summary to this path")
    parser.add_argument("--output-md", help="Write Markdown summary to this path")
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    rows = load_jsonl(corpus_path)
    summary = summarize(rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False)
    print(rendered)

    if args.output_json:
        Path(args.output_json).write_text(rendered + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(to_markdown(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
