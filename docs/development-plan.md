# Plan de développement

Légende : ✅ terminé et vérifié · 🟡 fait, vérification partielle · ⬜ à faire. « Vérifié » signifie : exécuté et constaté (tests, requêtes réelles ou
navigateur), pas seulement écrit.

## Phases

| # | Phase | État | Preuve de vérification |
|---|---|---|---|
| 1 | Audit du dépôt, lecture de la cartographie, sondage réel des sources | ✅ | [source-feasibility.md](source-feasibility.md) (22 sources, vérifiées le 21/10/2026) |
| 2 | Fondations : modèles SQLAlchemy, migration Alembic, configuration | ✅ | `alembic upgrade/downgrade/check` sur PostgreSQL et SQLite ; `tests/test_migrations_config.py` |
| 3 | Moteur de collecte : contrat, client HTTP poli, runner, logs, normalisation | ✅ | `tests/test_http_robots.py`, `tests/test_runner.py` |
| 4 | Sources prioritaires (10 connecteurs) | ✅ | Tests sur fixtures de pages réelles + 10/10 `health_check` en direct (`pytest -m network`) + collecte complète sur PostgreSQL |
| 5 | Déduplication, enrichissement, score, fraîcheur | ✅ | `tests/test_ingest_dedupe.py`, `test_scoring.py`, `test_dates_freshness.py`, `test_text_enrich.py` ; doublons inter-sources observés en réel |
| 6 | API FastAPI complète | ✅ | `tests/test_api.py` (39 tests) |
| 7 | Interface Next.js (6 pages) | ✅ | Contrôle navigateur (bureau 1440 px, mobile 375 px, clair/sombre, aucun débordement horizontal), `next build`, 20 tests Vitest |
| 8 | Veille automatique (bail, rattrapage, état réel, worker) | ✅ | `tests/test_scheduler.py` (24 tests) ; **non vérifiée sur plusieurs cycles de 6 h réels** |
| 9 | Docker (images backend/frontend, compose) | 🟡 | Voir `project_state.md` pour le résultat du démarrage de la pile complète |
| 10 | Documentation et rapport de livraison | ✅ | README, ce dossier, `project_state.md` |

## Qualité

- Backend : 249 tests (SQLite et PostgreSQL) + 10 tests « network » exclus par défaut ; `ruff check` propre.
- Frontend : `tsc --noEmit`, `eslint`, 20 tests Vitest, `next build`.
- Non couvert : tests de bout en bout automatisés du navigateur (Playwright) ; la vérification de l'interface a été faite à la main dans le navigateur.

## Prochaines tâches recommandées

1. **Valider les risques juridiques** : Emploi Dakar (CGU « usage personnel et privé, pas d'extraction de la base ») — décider d'accepter le risque
   pour un usage strictement personnel ou de demander l'accord écrit de Carriere360.
2. **Décider du dépôt public** : `backend/tests/fixtures/` contient des extraits de pages tierces ; garder, anonymiser ou passer le dépôt en privé.
3. **Ajuster les profils par défaut** (`config/default_search_profiles.yaml`) : compétences, niveaux et contrats sont des hypothèses.
4. **Laisser tourner la veille** quelques jours (mode `worker`) et relire l'historique : confirmer l'intervalle de 6 h, les sauts « collectée récemment »,
   l'absence de sources durablement bloquées.
5. **Sources différées** à retester : SeneJobs (404), Socium Job (530), RecrutSen (application JavaScript : Playwright seulement si l'accès automatisé est autorisé), TechCabal (widget dynamique).
6. **Pages carrière des employeurs** : `config/employers.yaml` ne contient que des URL réellement vérifiées ; un connecteur dédié par employeur dont la page publie des offres.
7. **Vague régionale** (Afrique de l'Ouest) : activer les pays voisins profil par profil ; sources locales à étudier pays par pays.
8. Tests de bout en bout (Playwright) sur les parcours : lancer une collecte, filtrer, changer le statut d'une offre, activer la veille.
