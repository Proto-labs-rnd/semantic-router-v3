#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

CORPUS="$TMPDIR/corpus.jsonl"
OUT_JSON="$TMPDIR/report.json"
OUT_MD="$TMPDIR/report.md"

cat > "$CORPUS" <<'EOF'
{"id":"c1","query":"run skill-index.py","live_route":"monitoring","expected_route":"dev_request"}
{"id":"c2","query":"deploy router-monitor.sh","live_route":"monitoring","expected_route":"ops_request"}
{"id":"c3","query":"why does the shadow log keep correcting routes","live_route":"agent_communication","expected_route":"monitoring"}
EOF

python3 "$ROOT/tools/prefilter-registry-drift-linter.py" "$CORPUS" --output-json "$OUT_JSON" --output-md "$OUT_MD" >/dev/null

python3 - "$OUT_JSON" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert not data['static']['errors'], data['static']
assert data['registry']['rules'] >= 10, data['registry']
assert data['corpus']['rows'] == 3, data['corpus']
assert data['corpus']['collision_rows'] >= 2, data['corpus']
assert data['corpus']['route_conflict_rows'] >= 1, data['corpus']
assert 'explicit_health_check' in data['corpus']['dead_rules'], data['corpus']['dead_rules']
assert 'tool_domain_lookup' in data['corpus']['winner_hits'] or 'tool_domain_lookup' in data['corpus']['never_win_rules'], data['corpus']
PY

grep -q "Prefilter Registry Drift Linter" "$OUT_MD"
grep -q "Route-conflict rows" "$OUT_MD"
echo "OK"
