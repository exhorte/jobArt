# Architecture

Application web **locale et mono-utilisateur** : le backend collecte des offres sur des sources publiques, les normalise, les
dédoublonne, les note par rapport à des profils de recherche, puis le frontend les présente. Ce document décrit l'architecture
**réelle** du code ; l'état des sources est dans [source-feasibility.md](source-feasibility.md), l'avancement dans
[development-plan.md](development-plan.md).

```
                    ┌────────────────────────── navigateur ──────────────────────────┐
                    │  Next.js (App Router, TypeScript, Tailwind, shadcn/ui)         │
                    └──────────────┬─────────────────────────────────────────────────┘
                                   │  /api/*  (même origine)
                    ┌──────────────▼───────────────┐
                    │ frontend : proxy app/api/[...path]/route.ts  → BACKEND_URL (lu à l'exécution)
                    └──────────────┬───────────────┘
                                   │ HTTP
 ┌─────────────────────────────────▼──────────────────────────────────────────────┐
 │ backend (FastAPI, Python)                                                      │
 │  api/*  ──► services/views (lecture)      services/runner (collecte asynchrone)│
 │                                            │                                   │
 │  jobs/scheduler (veille, bail en base)     ├─► collectors/* (1 connecteur/source)
 │  jobs/worker  (processus dédié, option)    │      └─ collectors/http (client poli, robots.txt)
 │                                            └─► services/ingest ─► dedupe, enrich, scoring, freshness
 └───────────────┬────────────────────────────────────────────────────────────────┘
                 │ SQLAlchemy (sync) + Alembic
          ┌──────▼──────┐
          │ PostgreSQL  │   (SQLite uniquement pour les tests rapides)
          └─────────────┘
```

## Décisions structurantes

| Sujet | Décision | Raison / compromis |
|---|---|---|
| Base de données | PostgreSQL (compose, port hôte 54330) ; SQLite réservé aux tests | Un seul stockage de référence. Les 249 tests passent sur les deux. |
| Accès BD | SQLAlchemy 2 **synchrone** + psycopg 3, Alembic | Simplicité. Les écritures depuis le code asynchrone passent par `asyncio.to_thread`. |
| Collecte | `httpx` asynchrone, une tâche par source, concurrence bornée | Les sources sont indépendantes : une erreur n'arrête jamais les autres. |
| Collecte longue | Asynchrone : `POST /api/search-runs` rend un identifiant, le frontend interroge `GET /api/search-runs/{id}` | Aucune requête HTTP ne reste ouverte pendant la collecte. |
| Authentification | Local : aucune (outil personnel). Public : verrou HTTP Basic devant le frontend (`frontend/proxy.ts`) + jeton `Authorization: Bearer` exigé par l'API (`api/security.py`) | En local l'API écoute sur 127.0.0.1. Un frontend public (Vercel) exige `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD` et se verrouille sinon ; un backend public exige `API_TOKEN` (refus de démarrer sans lui sur Render ou avec `REQUIRE_API_TOKEN=1`), que le proxy Next ajoute via `BACKEND_API_TOKEN`. `/api/health` reste libre. |
| Frontend → API | Proxy Next (`app/api/[...path]`) avec `BACKEND_URL` lu **à l'exécution** | Une même image Docker sert tous les environnements ; pas de CORS ; le navigateur ne connaît que le frontend. |
| Rendu | Pages client avec `fetch` + rafraîchissement adaptatif | Les données sont locales et changent pendant les collectes ; pas de rendu serveur à synchroniser. |
| LLM | Aucun dans le MVP | Score et déduplication sont déterministes et explicables. |

## Backend

### Modules (`backend/jobart/`)

| Module | Rôle |
|---|---|
| `main.py` | Fabrique `create_app` : initialisation (`bootstrap`), services partagés, démarrage de la veille si `SCHEDULER_MODE=embedded`. |
| `api/*` | Routeurs fins : `health` (santé, méta, tableau de bord), `sources`, `profiles`, `offers`, `runs`, `scheduler`. |
| `schemas/*` | Modèles Pydantic d'entrée/sortie. Les entrées sont validées strictement (ex. pays ISO à 2 lettres, listes bornées). |
| `models.py` | Modèle relationnel SQLAlchemy (voir ci-dessous). |
| `core/` | `config` (variables d'environnement), `db`, `errors` (taxonomie), `clock`, `log`. |
| `collectors/` | Contrat `Connector`, client HTTP poli, extracteur JSON-LD, registre blanc, un module par source. |
| `services/runner.py` | Moteur de collecte (`RunService`). |
| `services/ingest.py` | Persistance : création/mise à jour, déduplication, scores, statuts. |
| `services/{dedupe,scoring,freshness,enrich,text,urls,dates,geo}.py` | Logique métier pure (testée sans réseau ni base quand c'est possible). |
| `services/views.py` | Requêtes de lecture : liste filtrée, détail, état des sources, tableau de bord. |
| `jobs/scheduler.py`, `jobs/worker.py` | Veille automatique (voir plus bas). |

### Modèle de données

`search_profiles` · `job_sources` · `job_offers` (annonce **unique**) · `job_offer_sources` (une ligne par publication de l'annonce sur une
source : URL d'origine, date déclarée par cette source, dernière observation) · `offer_url_keys` (alias d'URL pour la déduplication) ·
`offer_scores` (un score par couple annonce × profil, avec le détail) · `saved_jobs` (suivi utilisateur : statut, notes) ·
`search_runs` / `search_run_sources` (historique et résultat par source) · `scheduler_state` (ligne unique : réglages et bail de la veille).

Principes : l'annonce unique est séparée de ses publications (on conserve **toutes** les sources originales) ; les dates sont distinguées
(publication déclarée / première détection / dernière observation / dernière vérification / date limite) ; rien n'est supprimé automatiquement.

### Contrat d'un connecteur

```python
class Connector(ABC):
    source_key; source_name; source_url; allowed_hosts      # hôtes seuls contactables
    async def search(params: SearchParameters) -> list[RawJob]       # réseau
    def normalize(raw: RawJob) -> NormalizedJob                       # pur, testable sur fixtures
    async def health_check() -> HealthResult                          # une requête, rien n'est enregistré
```

- `SearchParameters` est l'union des profils applicables (mots-clés entrelacés pour que chaque profil soit représenté même si la
  source plafonne le nombre de requêtes).
- `NormalizedJob` est le schéma commun : les champs inconnus restent vides (jamais inventés) ; `estimated_fields` liste ce qui est **déduit**
  par jobArt et non déclaré par la source.
- Les connecteurs sont **enregistrés explicitement** dans `collectors/registry.py`. Aucun endpoint n'accepte une URL fournie par le client
  (sauf l'ajout manuel, qui n'émet aucune requête vers l'URL).
- Ajouter une source : créer le module, l'enregistrer, ajouter l'entrée dans `config/sources.yaml`, écrire des tests sur fixtures réelles,
  régénérer `docs/source-feasibility.md`.

### Client HTTP poli (`collectors/http.py`)

Hôtes autorisés par source (redirections contrôlées) · `robots.txt` consulté et respecté (RFC 9309 : jokers, règle du plus long motif,
`Crawl-delay`) · délai minimal par hôte · concurrence bornée · timeouts, une reprise sur erreur transitoire · taille de réponse bornée ·
défi anti-robot, CAPTCHA, 401/403 → `AccessBlocked`, **jamais contourné**. Les descriptions d'annonces sont du contenu tiers non fiable :
le frontend les affiche en texte brut.

### Moteur de collecte (`services/runner.py`)

1. `create_run` (rapide) : valide la demande, crée un `SearchRun` en file et une ligne `SearchRunSource` par source.
2. `execute_run` (tâche de fond) : pour chaque source, avec concurrence bornée :
   verrou par source en base (bail, évite deux collectes simultanées de la même source, même entre processus) → intervalle minimal
   éventuel (`min_interval_minutes`) → `search` sous délai global → `normalize` (un enregistrement invalide est rejeté seul) →
   `ingest` → statistiques. Une exception d'une source est consignée (type d'erreur stable) et n'affecte pas les autres.
3. Fin : agrégats et statut `completed` (aucune source en échec) | `partial` | `failed` (aucune réussite) | `interrupted`.
   Une réponse vide n'est **pas** une erreur.
4. Battement de cœur toutes les 20 s ; une exécution sans battement récent est déclarée « interrompue » (`reap_stale_runs`) au démarrage et à
   chaque tick de la veille.

Taxonomie d'erreurs (`core/errors.py`) : `network`, `timeout`, `unavailable`, `blocked`, `rate_limited`, `robots_disallowed`, `parse`,
`normalization`, `locked`, `skipped_recent`, `internal`.

### Déduplication (`services/dedupe.py`)

Quatre niveaux, **prudents** (dans le doute on garde les annonces séparées) :

1. identifiant d'annonce de la source (même source) ;
2. URL normalisée, y compris les URL équivalentes déclarées par la source (`sameAs`) — toutes sources ;
3. identité : entreprise + titre + localisation normalisés (entreprise connue des deux côtés, **jamais** deux annonces de la même source,
   dates de publication à moins de 45 jours, candidat ambigu → aucune fusion) ;
4. similarité : titre ≥ 0,92, ou ≥ 0,80 avec descriptions quasi identiques (Jaccard ≥ 0,75, au moins 60 mots distincts).

Si l'entreprise n'est connue qu'ensuite, une fusion a posteriori est possible. Les sources d'origine restent toutes rattachées à l'annonce.

### Score de pertinence (`services/scoring.py`)

Déterministe, sur 100, **par profil** : `points obtenus / points possibles` selon les critères applicables au profil.
Poids par défaut : métier 30 · compétences 25 · localisation 15 · expérience 10 · secteur 10 · contrat et mode 10 (surchargeables par profil ;
0 désactive un critère). Règles clés :

- une information **absente** de l'annonce vaut 0 et est listée dans « informations manquantes » : jamais un point positif ;
- un mot exclu dans le titre met le score à 0, dans la description retire 20 points ;
- le salaire n'est pas un critère ;
- le détail (points par critère, mots trouvés, manquants, restrictions) est stocké et affiché : le score est explicable.

C'est une proximité avec les critères du profil, pas une probabilité d'embauche. Toute modification de profil recalcule les scores en arrière-plan.

### Fraîcheur et cycle de vie (`services/freshness.py`)

- Fraîcheur : calculée **uniquement** sur la date de publication déclarée (≤ 7 j récente, ≤ 30 j assez récente, sinon ancienne ; sans date : « date inconnue »).
- Cycle de vie observé : `listed` (vue à la dernière collecte) · `stale` (plus listée par une source collectée depuis ≥ 14 jours) ·
  `deadline_passed` · `closed` (clôture indiquée par la source). Une URL qui répond ne prouve pas qu'une offre est ouverte : on ne dit jamais « active ».

### Veille automatique (`jobs/scheduler.py`, `jobs/worker.py`)

- Réglages **persistants** (table `scheduler_state`) : activée ?, intervalle (30 min à 7 j, défaut 6 h), profils et sources ciblés. Désactivée par défaut.
- **Bail en base** (`lease_owner` / `lease_expires_at`, acquisition atomique) : un seul processus déclenche, même si plusieurs démarrent.
- Un *tick* APScheduler (30 s) renouvelle le bail et le battement de cœur, nettoie les exécutions orphelines et lance une collecte quand
  `next_run_at` est dépassé. Après un arrêt : **une seule** collecte de rattrapage (pas de rafale). Si une collecte est en cours : report au tick suivant.
- **État réel** : `running` seulement si battement récent ET bail valide ; sinon « activée mais arrêtée ». Le frontend ne prétend jamais qu'elle tourne.
- Deux modes : `SCHEDULER_MODE=embedded` (l'API porte la veille) ou `off` + `python -m jobart.jobs.worker` (la veille survit à un redémarrage de l'API).

## Frontend (`frontend/`)

Next.js (App Router) + TypeScript + Tailwind v4 + composants shadcn/ui, design système monochrome (thème clair/sombre sans flash, Inter, Lucide).

| Page | Contenu |
|---|---|
| `/` Tableau de bord | Indicateurs réels, meilleures correspondances, sources en erreur, répartitions, dernière collecte, état de la veille. |
| `/offers` | Liste filtrable (mots-clés, profil, source, pays, ville, entreprise, contrat, mode, statut, score, dates), tri, pagination ; filtres dans l'URL ; ajout manuel. |
| `/offers/[id]` | Fiche : dates distinguées, sources d'origine, explication du score par profil, suivi (statut, notes), lien vers l'annonce d'origine. |
| `/profiles` | Création, modification, duplication, activation, suppression. |
| `/sources` | État par source (actives, désactivées, à vérifier, inaccessibles, en erreur, exclues), test, collecte ciblée, raison des exclusions ; employeurs ciblés. |
| `/runs` | Historique, suivi en direct d'une exécution, détail par source (erreurs, avertissements). |
| `/scheduler` | État réel de la veille, activation, intervalle, périmètre, prochaine exécution. |

Les liens externes s'ouvrent dans un nouvel onglet avec `rel="noopener noreferrer"` et uniquement en `http(s)`.

## Sécurité et conformité

- Pas d'authentification : usage local uniquement ; les ports Docker ne sont publiés que sur `127.0.0.1`.
- Pas de contournement de CAPTCHA, d'authentification ni de blocage anti-robot ; `robots.txt` respecté ; débit limité.
- Sources dont les conditions interdisent l'extraction : **exclues** et documentées ; solution de repli = ajout manuel d'une annonce.
- Secrets : `.env` non versionné ; la configuration des sources (`config/*.yaml`) est publique, sans secret.
- Dépôt public : `backend/tests/fixtures/` contient des extraits tronqués de pages publiques tierces (voir README, « Limites »).
