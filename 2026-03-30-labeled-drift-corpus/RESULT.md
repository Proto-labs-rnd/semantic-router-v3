# RESULT — Labeled Drift Corpus

**Expérience:** Labeled Drift Corpus  
**Statut:** ✅ Succès net  
**Durée:** ~40 min  
**Verdict:** Pas `[PROMOTE]` — bon outil de calibration, mais corpus encore partiellement synthétique et non encore revu humainement ligne par ligne.

## Ce qui a été livré
- `tools/labeled-drift-corpus.py` — construit un corpus annoté à partir du log shadow réel + cas synthétiques ciblés
- `tools/test-labeled-drift-corpus.sh` — test de non-régression sur le vrai log Router V3 shadow
- `experiments/2026-03-30-labeled-drift-corpus/labeled-corpus.jsonl` — corpus final annoté
- `experiments/2026-03-30-labeled-drift-corpus/corpus-summary.json` — métriques exploitables
- `experiments/2026-03-30-labeled-drift-corpus/corpus-report.md` — rapport détaillé

## Validation réelle
Commandes exécutées :
```bash
python3 -m py_compile tools/labeled-drift-corpus.py
./tools/test-labeled-drift-corpus.sh
python3 tools/labeled-drift-corpus.py \
  --shadow-log experiments/2026-03-30-router-planner-drift-dashboard/router-shadow.ndjson \
  --output-jsonl experiments/2026-03-30-labeled-drift-corpus/labeled-corpus.jsonl \
  --output-json experiments/2026-03-30-labeled-drift-corpus/corpus-summary.json \
  --output-md experiments/2026-03-30-labeled-drift-corpus/corpus-report.md
```

Résultats réels :
- Corpus final : **58 requêtes** = **22 observées** + **36 synthétiques**
- Cas décisifs : **52**
- Accuracy live sur cas décisifs : **11.5%**
- Accuracy planner sur cas décisifs : **88.5%**
- Accuracy observée seule : **live 30.0%** vs **planner 70.0%**
- Corrections décisives : **40**, dont **40 sauvées par le planner**, **0 dégradation nette**
- Gaps structurants : **5 cas meta-routing** où aucun système n’est clairement satisfaisant

## Découvertes clés
- Le vrai gain du planner n’est pas “un peu meilleur routing”, mais une correction systématique de trois familles :
  1. `agent_communication -> research_query`
  2. `agent_communication -> dev_request`
  3. `monitoring -> dev_request`
- Le corpus révèle un trou de modélisation distinct : les requêtes **méta sur le routing** ne rentrent proprement ni dans `agent_communication` ni dans `monitoring`
- Le drift est surtout causé par trois mécanismes robustes :
  - `keyword_hijack`
  - `monitoring_overgeneralization`
  - `infrastructure_health_overreach`
- Le bon prochain pas n’est pas encore de promouvoir le planner live, mais de **fermer le gap meta-routing** puis de synchroniser les constantes/router rules avec les paires dominantes

## Décision
- **Pas de `[PROMOTE]`** cette session
- Le corpus est assez solide pour guider le tuning, mais pas assez “vérité terrain” pour justifier une promotion live sans revue humaine des annotations

## Prochaines idées générées
1. **Meta-Routing Prefilter** — détecter les requêtes sur le système de routing lui-même avant le routeur principal
2. **Shared Router Constants** — fermer le drift silencieux entre routeur live et planner sur les paires dominantes
3. **Corpus Review Pass** — relire/annoter humainement les 22 cas observés puis élargir le corpus réel avant tout changement live
