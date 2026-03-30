# Labeled Drift Corpus — router-shadow.ndjson

## Corpus
- Total rows: 58 (22 observed + 36 synthetic)
- Decisive rows: 52
- Ambiguous rows: 6

## Route accuracy on decisive rows
- Live router: 11.5%
- Planner route: 88.5%
- Observed-only live: 30.0%
- Observed-only planner: 70.0%

## Corrections
- Corrected rows: 44
- Planner saved: 40
- Planner harmed: 0
- Neither correct: 0
- Ambiguous corrected rows: 4
- Planner precision on decisive corrections: 100.0%

## Clarify noise
- Clarify total: 17
- Legitimate: 17
- Noise: 0 (0.0%)
- Avoidable cases in corpus: 35

## Top drift mechanisms
- keyword_hijack: 24
- monitoring_overgeneralization: 14
- infrastructure_health_overreach: 7
- meta_routing: 4
- agent_affinity_bias: 3

## Family slices
- meta_routing: count=6 | live=25.0% | planner=25.0% | ambiguous=2 | clarify_noise=0 | labels={'neither_correct': 3, 'ambiguous': 2, 'live_correct': 1}
- dev_maintenance: count=4 | live=0.0% | planner=50.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3, 'neither_correct': 1}
- research: count=4 | live=25.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3, 'live_correct': 1}
- agent_affinity_router_topic: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- boundary_dev_research: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- boundary_monitoring_research: count=3 | live=0.0% | planner=100.0% | ambiguous=2 | clarify_noise=0 | labels={'ambiguous': 2, 'planner_correct': 1}
- clarify_noise_clear_dev_intent: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- clarify_noise_explicit_tool: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- semantic_agentcomm_research: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- semantic_agentcomm_research_delegation: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}
- synonym_infra_monitoring: count=3 | live=0.0% | planner=100.0% | ambiguous=2 | clarify_noise=0 | labels={'ambiguous': 2, 'planner_correct': 1}
- synonym_monitoring_infra: count=3 | live=0.0% | planner=100.0% | ambiguous=0 | clarify_noise=0 | labels={'planner_correct': 3}

## Priority rules
- agent_communication->research_query: planner wins 9 vs live 0 → review route rules / shared constants for this drift pair
- agent_communication->dev_request: planner wins 8 vs live 0 → review route rules / shared constants for this drift pair
- monitoring->dev_request: planner wins 7 vs live 0 → review route rules / shared constants for this drift pair
- meta_routing: 5 rows where neither system is clearly right → add a meta-routing prefilter or a dedicated route bucket

## Sample planner wins
- `verify skill index freshness and sync it` | monitoring → dev_request | family=dev_maintenance | mechanism=monitoring_overgeneralization
- `check context saturation before heavy task` | monitoring → experiment_request | family=infra_guard | mechanism=monitoring_overgeneralization
- `research how the router works` | agent_communication → research_query | family=research | mechanism=keyword_hijack
- `run router v3 test suite` | agent_communication → dev_request | family=dev_testing | mechanism=keyword_hijack
- `monitor router latency and stats` | infrastructure_health → monitoring | family=monitoring | mechanism=infrastructure_health_overreach
- `explain router architecture tradeoffs` | agent_communication → research_query | family=research | mechanism=keyword_hijack
- `sync the skill index if it is stale` | monitoring → dev_request | family=dev_maintenance | mechanism=monitoring_overgeneralization
- `who should handle research on router design` | agent_communication → research_query | family=research | mechanism=keyword_hijack
- `rebuild the skill index from scratch` | monitoring → dev_request | family=tool_signal_monitoring_dev | mechanism=monitoring_overgeneralization
- `run skill-index.py with --full-scan flag` | monitoring → dev_request | family=tool_signal_monitoring_dev | mechanism=monitoring_overgeneralization

## Meta-routing gaps
- `route this message to Tachikoma` | live=agent_communication | planner=agent_communication | label=ambiguous
- `show which router queries planner keeps correcting` | live=agent_communication | planner=agent_communication | label=ambiguous
- `which route pairs mismatch most often` | live=agent_communication | planner=agent_communication | label=neither_correct
- `should this query go to specter or tachikoma` | live=monitoring | planner=monitoring | label=neither_correct
- `what tool should execute router tests` | live=agent_communication | planner=agent_communication | label=neither_correct
