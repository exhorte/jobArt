# État du projet jobArt (mis à jour le 22/10/2026)

> **Renommage du 22/10/2026** : le projet s'appelle désormais **jobArt** (ex-JobRadar). Détail et reprise : `../05_memoire_session/2026-10-22_renommage_jobart.md`.

## Hébergement public (22/10/2026)
- **Frontend** : projet Vercel `jobart` (équipe `exhorte's projects`, racine `frontend`, région `fra1`), déployé à chaque push sur `main` de `exhorte/jobArt`. Verrou HTTP Basic obligatoire (`frontend/proxy.ts`) : vérifié en ligne (401 sans identifiants, 200 avec).
- **Backend** : service Render `jobart-api` (Docker, plan free, Frankfurt) + base `jobart-db` (PostgreSQL 17, plan free, **supprimée le 21/11/2026** sauf passage à un plan payant). L'API exige `API_TOKEN` (`Authorization: Bearer`, ajouté par le proxy Next via `BACKEND_API_TOKEN`).
- **En service depuis le 22/10/2026** : `DATABASE_URL` renseignée, `/api/health` ok, protection par jeton vérifiée (401 sans jeton, 404 sur `/openapi.json`), chaîne Vercel → Render vérifiée. Première collecte (n° 1, lancée depuis le site public) : statut `partial`, **225 offres créées** sur 230 trouvées (5 doublons), 8 sources sur 10 réussies.
- **Deux sources bloquées depuis Render** : `emploisenegal` et `expat_dakar` répondent HTTP 403 (défi anti-robot) à l'adresse du datacenter Render ; elles réussissent en local (27 et 2 offres). Conformément à la règle du projet, ce blocage n'est pas contourné. Pour ces deux sources, collecter depuis la machine locale ou accepter une couverture partielle sur le site public.
- Le plan free de Render endort le service après inactivité : la veille automatique ne tourne pas pendant le sommeil (plan Starter nécessaire pour une veille continue).
- Identifiants (verrou, jeton) : fichier local `.env.deploy` (non versionné) et variables des hébergeurs.

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
- Backend : 258 passés sur SQLite (249 au 21/10 sur SQLite **et** PostgreSQL, base `jobradar_test`, nom d'avant le renommage ; +9 tests du jeton d'API le 22/10) ; `ruff check` propre ; 10 tests `network` passés séparément.
- Frontend : `tsc`, `eslint`, 27 tests Vitest (dont 7 du verrou d'accès), `next build` OK.
- Doc : `scripts/gen_source_feasibility.py --check` à jour.

## Problèmes connus / non vérifié
- Veille jamais observée sur plusieurs cycles de 6 h réels.
- Écart au plan : l'interface ne permet pas de lancer une collecte **sur un profil précis** (l'API `profile_id` existe et est testée).
- Pas de tests de bout en bout automatisés du navigateur.
- `npm audit` : vulnérabilités de dépendances de développement (`eslint-config-next`), hors image de production.
- Emploi Dakar : CGU « usage personnel et privé » — risque à valider par l'utilisateur.
- Dépôt GitHub public contenant des fixtures de pages tierces — décision à prendre.
- Profils par défaut = hypothèses à valider.
- **Git** : `04_code/` est son propre dépôt (remote `exhorte/jobArt`, branche `main`) ; le dépôt de la racine `C:\Dev\jobart` (notes privées) est local, sans remote.
- La veille peut être sautée sous charge (délai de grâce APScheduler de 1 s) : correctif prévu (backlog B12).

## Sources
Intégrées (10) : Emploi Dakar, Emploi Sénégal, Africarrières SN, SenJob SN, ConcourSN, Expat-Dakar, Remote4Africa, Himalayas, Remote OK, Wave.
Différées : SeneJobs (404), RecrutSen (SPA), Socium Job (530), TechCabal (widget JS). Exclues (CGU/robots) : Remotive, Remote Rocketship, Wellfound, LinkedIn, Jobberman,
Career List Africa, Impactpool. Détail : [docs/source-feasibility.md](docs/source-feasibility.md).

## Prochaine tâche prioritaire
Décider du sort des deux sources bloquées depuis Render, activer la veille sur le site public si souhaité ; trancher les questions ouvertes (plan payant Render pour la veille, CGU Emploi Dakar, fixtures de pages tierces, profils par défaut) ; ensuite laisser tourner la veille quelques jours.
Liste complète : [docs/development-plan.md](docs/development-plan.md).
