# État du projet jobArt (mis à jour le 21/10/2026)

> **Renommage du 22/10/2026** : le projet s'appelle désormais **jobArt** (ex-JobRadar). Déploiement Vercel du frontend **pas encore fait** : en attente de décisions (hébergement du backend et de la base, protection d'accès). Détail et reprise : `../05_memoire_session/2026-10-22_renommage_jobart.md`.

## Objectif
Agrégateur personnel (local, mono-utilisateur) d'offres d'emploi, Sénégal d'abord : collecte réelle, normalisation, déduplication, score /100 explicable,
veille automatique (6 h configurable), interface Next.js. Consigne : `../02_ressource/project plan.md` (PARTIE 5).

## Architecture actuelle
FastAPI + SQLAlchemy 2 (sync) + PostgreSQL ; connecteurs httpx async ; veille APScheduler à bail en base ; frontend Next.js 16 avec proxy `/api`.
Détail : [docs/architecture.md](docs/architecture.md).

## Fonctionnalités terminées et vérifiées
- 10 connecteurs réels (tests sur fixtures + `pytest -m network` 10/10 le 21/10/2026 + collecte complète sur PostgreSQL : 246 offres).
- Moteur de collecte, déduplication 4 niveaux, score, fraîcheur, API complète, veille (bail, rattrapage, état réel), worker dédié (`jobs/worker.py`).
- Interface : 6 pages + fiche d'offre, contrôlées dans le navigateur (1440 px et 375 px, clair/sombre, aucun débordement horizontal).
- Docker : images backend/frontend construites, pile `db + backend + frontend` démarrée et saine, migrations auto, proxy OK, utilisateurs non-root ; worker optionnel testé (bail exclusif).

## Tests exécutés (21/10/2026)
- Backend : 249 passés sur SQLite **et** sur PostgreSQL (base `jobradar_test`, nom d'avant le renommage) ; `ruff check` propre ; 10 tests `network` passés séparément.
- Frontend : `tsc`, `eslint`, 20 tests Vitest, `next build` OK.
- Doc : `scripts/gen_source_feasibility.py --check` à jour.

## Problèmes connus / non vérifié
- Veille jamais observée sur plusieurs cycles de 6 h réels.
- Écart au plan : l'interface ne permet pas de lancer une collecte **sur un profil précis** (l'API `profile_id` existe et est testée).
- Pas de tests de bout en bout automatisés du navigateur.
- `npm audit` : vulnérabilités de dépendances de développement (`eslint-config-next`), hors image de production.
- Emploi Dakar : CGU « usage personnel et privé » — risque à valider par l'utilisateur.
- Dépôt GitHub public contenant des fixtures de pages tierces — décision à prendre.
- Profils par défaut = hypothèses à valider.
- **Git** : le dépôt est maintenant **à la racine** (`C:\Dev\jobart`, remote `exhorte/jobart`, branche `main`) ; le travail a été commité le 21/10 avec l'application à la racine. Le 22/10 l'arborescence a été remise à l'état d'origine (code dans `04_code/`) : git voit des déplacements non enregistrés. Structure du dépôt public (notes privées dans l'historique) à décider.
- La veille peut être sautée sous charge (délai de grâce APScheduler de 1 s) : correctif prévu (backlog B12).

## Sources
Intégrées (10) : Emploi Dakar, Emploi Sénégal, Africarrières SN, SenJob SN, ConcourSN, Expat-Dakar, Remote4Africa, Himalayas, Remote OK, Wave.
Différées : SeneJobs (404), RecrutSen (SPA), Socium Job (530), TechCabal (widget JS). Exclues (CGU/robots) : Remotive, Remote Rocketship, Wellfound, LinkedIn, Jobberman,
Career List Africa, Impactpool. Détail : [docs/source-feasibility.md](docs/source-feasibility.md).

## Prochaine tâche prioritaire
Relire et committer le travail, puis trancher les questions ouvertes (CGU Emploi Dakar, dépôt public, profils par défaut) ; ensuite laisser tourner la veille quelques jours.
Liste complète : [docs/development-plan.md](docs/development-plan.md).
