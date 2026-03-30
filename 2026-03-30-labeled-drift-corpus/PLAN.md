# PLAN — Labeled Drift Corpus

## Goal
Construire un corpus annoté pour mesurer la qualité réelle des corrections planner/router avant toute évolution du routing live.

## Why now
- Le shadow mode et le dashboard existent déjà
- Les divergences sont observées mais pas encore jugées contre une vérité terrain
- Le prochain goulot est la mesure, pas un nouveau composant

## Deliverables
1. Un corpus JSONL annoté (queries existantes + cas synthétiques ciblés)
2. Un outil local pour calculer des métriques de drift/correction/clarify-noise
3. Un rapport Markdown avec priorités de correction

## Validation
- Corpus >= 50 requêtes
- Rapport chiffré par famille de drift
- Sortie exploitable pour décider des prochaines modifications router/planner

## Constraints
- R&D only
- Pas de changement live du routing
- Toute analyse/synthèse lourde déléguée à Hermes
