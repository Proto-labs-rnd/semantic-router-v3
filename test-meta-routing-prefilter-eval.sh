#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

CORPUS="$TMPDIR/corpus.jsonl"
OUT_JSON="$TMPDIR/out.json"
OUT_MD="$TMPDIR/out.md"

cat > "$CORPUS" <<'EOF'
{"id":"t1","query":"run skill-index.py","live_route":"monitoring","expected_route":"dev_request","label":"planner_correct","source":"synthetic","family":"tool_signal_monitoring_dev","clarify_legitimate":false}
{"id":"t2","query":"deploy the new router binary to staging","live_route":"agent_communication","expected_route":"ops_request","label":"planner_correct","source":"synthetic","family":"agent_affinity_router_topic","clarify_legitimate":true}
{"id":"t3","query":"which route pairs mismatch most often","live_route":"agent_communication","expected_route":"monitoring","label":"neither_correct","source":"observed","family":"meta_routing","clarify_legitimate":true}
{"id":"t4","query":"server CPU usage too high","live_route":"infrastructure_health","expected_route":"infrastructure_health","label":"live_correct","source":"observed","family":"infra_alert","clarify_legitimate":true}
EOF

python3 "$ROOT/tools/meta-routing-prefilter-eval.py" "$CORPUS" --output-json "$OUT_JSON" --output-md "$OUT_MD" >/dev/null

python3 - "$OUT_JSON" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    data = json.load(handle)
assert data['registry']['rules'] >= 10, data['registry']
assert data['registry']['tools'] >= 5, data['registry']
assert data['metrics']['prefilter_alignment_full'] == 100.0, data['metrics']
assert data['metrics']['prefilter_alignment_decisive'] == 100.0, data['metrics']
assert data['metrics']['prefilter_alignment_observed'] == 100.0, data['metrics']
assert data['metrics']['prefilter_deflection_rate'] == 75.0, data['metrics']
assert data['rules']['explicit_tool_invocation'] >= 1, data['rules']
assert data['rules']['ops_verb_gate'] >= 1, data['rules']
assert data['rules']['meta_drift_monitoring'] >= 1, data['rules']
PY

grep -q "Meta-Routing Prefilter Evaluation" "$OUT_MD"
grep -q "## Registry" "$OUT_MD"
echo "OK"
