#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/shared-storage/openclaw/workspace-labs"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

JSONL="$TMPDIR/corpus.jsonl"
JSON="$TMPDIR/summary.json"
MD="$TMPDIR/report.md"

python3 "$ROOT/tools/labeled-drift-corpus.py" \
  --shadow-log "$ROOT/experiments/2026-03-30-router-planner-drift-dashboard/router-shadow.ndjson" \
  --output-jsonl "$JSONL" \
  --output-json "$JSON" \
  --output-md "$MD" >/dev/null

python3 - <<'PY' "$JSONL" "$JSON" "$MD"
import json
import sys
from pathlib import Path

jsonl_path = Path(sys.argv[1])
json_path = Path(sys.argv[2])
md_path = Path(sys.argv[3])
rows = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
summary = json.loads(json_path.read_text())
md = md_path.read_text()

assert len(rows) == 58, f"expected 58 rows, got {len(rows)}"
assert summary["corpus"]["observed"] == 22, summary["corpus"]
assert summary["corpus"]["synthetic"] == 36, summary["corpus"]
assert summary["accuracy"]["planner_accuracy_decisive"] > summary["accuracy"]["live_accuracy_decisive"], summary["accuracy"]
assert summary["corrections"]["planner_saved"] > summary["corrections"]["planner_harmed"], summary["corrections"]
assert summary["clarify"]["avoidable_cases"] >= 1, summary["clarify"]
assert "Priority rules" in md, "markdown report missing priority section"
print("OK")
PY
