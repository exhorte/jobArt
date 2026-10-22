# jobArt

> Anciennement JobRadar (renommé le 22/10/2026). Les installations antérieures gardent leur base `jobradar` et leur volume : voir `PGDATA_VOLUME` dans `.env.example`.

Veille personnelle des offres d'emploi, **Sénégal d'abord** (extensible à l'Afrique de l'Ouest et au télétravail) : jobArt collecte des offres
réelles sur des sources publiques, les normalise, supprime les doublons, calcule un **score de pertinence explicable** par rapport à vos profils de
recherche et les présente dans une interface web. Une veille automatique (6 h par défaut, configurable) relance la collecte.

- Application **locale et mono-utilisateur** (aucune authentification : ne pas l'exposer sur Internet).
- **Aucune donnée fictive** : une information absente d'une annonce reste absente (« Date inconnue », score « non évalué »…).
- Respect des sources : `robots.txt`, débit limité, aucun contournement de CAPTCHA ni de connexion. Les sources dont les conditions interdisent
  l'extraction sont **exclues** et la raison est affichée ; pour celles-ci, l'ajout manuel d'une annonce reste possible.

| Document | Contenu |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Architecture réelle : composants, collecte, déduplication, score, veille |
| [docs/source-feasibility.md](docs/source-feasibility.md) | État et décision pour chacune des 22 sources étudiées (généré depuis `config/`) |
| [docs/development-plan.md](docs/development-plan.md) | Phases, vérifications, prochaines tâches |
| [project_state.md](project_state.md) | État courant du projet (à lire en premier pour reprendre le travail) |
| [CLAUDE.md](CLAUDE.md) | Instructions persistantes pour les assistants de code |

## Fonctionnalités

- **10 connecteurs réels** testés sur de vraies pages : Emploi Dakar, Emploi Sénégal, Africarrières Sénégal, SenJob Sénégal, ConcourSN, Expat-Dakar Emploi,
  Remote4Africa, Himalayas (API), Remote OK (API), Wave (page carrière). Une source en erreur n'empêche jamais les autres.
- **Déduplication prudente** (4 niveaux) : une offre publiée sur plusieurs sources n'apparaît qu'une fois, toutes ses sources d'origine sont conservées.
- **Score /100 par profil**, déterministe et détaillé (métier, compétences, lieu, expérience, secteur, contrat/mode).
- **Profils de recherche** modifiables dans l'interface (mots-clés, pays, villes, contrats, exclusions, pondérations).
- **Suivi** : statut (nouvelle, vue, sauvegardée, candidature envoyée, ignorée) et notes par offre.
- **Veille automatique** persistante, avec état réel (jamais « active » si aucun processus ne la porte) et historique détaillé par source.
- **Ajout manuel** d'une annonce (LinkedIn, source exclue) : le serveur ne visite jamais l'URL saisie.

## Prérequis

- Docker (PostgreSQL, et la pile complète si souhaité)
- Pour le développement sans conteneur applicatif : Python ≥ 3.12 (testé en 3.14), Node.js ≥ 22 (testé en 24), [`uv`](https://docs.astral.sh/uv/) (optionnel, pour régénérer le lock)

## Démarrage rapide (Docker : base + API + interface)

```bash
cp .env.example .env          # puis changer POSTGRES_PASSWORD (et la valeur dans DATABASE_URL pour le mode local)
docker compose up -d --build
```

Ouvrir <http://localhost:3000>. Les migrations sont appliquées automatiquement au démarrage de l'API. Aucune collecte ne part toute seule :
cliquer sur **Lancer une collecte** (barre supérieure) ou activer la veille dans **Veille automatique**.

```bash
docker compose logs -f backend        # journaux de l'API et de la collecte
docker compose down                   # arrêt (les données restent dans le volume pgdata)
```

Veille portée par un processus dédié (elle survit à un redémarrage de l'API) :

```bash
SCHEDULER_MODE=off docker compose --profile worker up -d --build
```

## Développement local (API et interface hors conteneur)

```bash
docker compose up -d db                                   # PostgreSQL sur 127.0.0.1:54330

# Backend
cd backend
uv venv && uv pip install -e ".[dev]"                     # ou : python -m venv .venv && pip install -e ".[dev]"
.venv/Scripts/python -m alembic upgrade head              # (Linux/macOS : .venv/bin/python)
.venv/Scripts/python -m uvicorn jobart.main:app --port 8000

# Frontend (autre terminal)
cd frontend
npm install
npm run dev                                               # http://localhost:3000, proxy /api -> http://127.0.0.1:8000
```

Si la veille est portée par un worker (`SCHEDULER_MODE=off`) : `python -m jobart.jobs.worker` dans un autre terminal.

> **Windows** : utiliser `127.0.0.1` et non `localhost` dans `DATABASE_URL` (la résolution de `localhost` ajoute ~30 s à chaque connexion).

## Configuration

Variables d'environnement (fichier `.env` à la racine, voir `.env.example`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` | `jobart` / — / `jobart` / `54330` | Base PostgreSQL du compose (port publié sur 127.0.0.1) |
| `DATABASE_URL` | `postgresql+psycopg://…@127.0.0.1:54330/jobart` | Connexion du backend **hors conteneur** (dans le compose, elle est composée automatiquement vers `db`) |
| `SCHEDULER_MODE` | `embedded` | `embedded` : l'API porte la veille ; `off` : un worker dédié la porte |
| `LOG_LEVEL` | `INFO` | Niveau de journalisation |
| `CORS_ORIGINS` | `http://localhost:3000` | Origines autorisées (inutile avec le proxy du frontend) |
| `HTTP_USER_AGENT` | `jobArt/0.1 (personal job watcher; respects robots.txt)` | Identité envoyée aux sites (vous pouvez y ajouter une adresse de contact) |
| `COLLECT_MAX_CONCURRENCY` | `3` | Sources collectées en parallèle |
| `REQUEST_TIMEOUT_SECONDS` / `SOURCE_TIMEOUT_SECONDS` | `20` / `240` | Délai par requête / par source |
| `MIN_REQUEST_DELAY_SECONDS` | `1.5` | Délai minimal entre deux requêtes vers un même site |
| `BACKEND_URL` (frontend) | `http://127.0.0.1:8000` | Adresse du backend vue par le serveur Next.js (lue à l'exécution) |

Fichiers de configuration versionnés (publics, sans secret) :

- `config/sources.yaml` : registre des sources (connecteur, décision, raison, conditions d'utilisation, paramètres) ;
- `config/employers.yaml` : employeurs ciblés et résultat de la vérification de leurs pages carrière ;
- `config/default_search_profiles.yaml` : profils créés au premier démarrage (valeurs **par défaut à ajuster** : ce sont des hypothèses).

## Utilisation

1. **Profils de recherche** : adaptez (ou créez) vos profils — mots-clés, pays, villes, contrats, exclusions. Seuls les profils **actifs** pilotent la collecte et le score.
2. **Sources** : activez/désactivez les sources, testez-en une (une requête, rien n'est enregistré), lancez une collecte ciblée. Les sources exclues ou
   différées affichent la raison de la décision.
3. **Lancer une collecte** : l'exécution est asynchrone ; l'**Historique** montre l'avancement source par source (erreurs, avertissements, doublons).
4. **Offres** : filtrez, triez, ouvrez le détail (score expliqué, sources d'origine, dates), changez le statut, ajoutez une note, ouvrez l'annonce d'origine.
5. **Veille automatique** : activez-la, choisissez l'intervalle (30 min à 7 jours, 6 h recommandé) ; la page affiche l'état réel du processus qui la porte.

Pour une offre vue sur une source exclue (LinkedIn…) : **Offres → Ajouter une annonce** (lien, intitulé, description collée).

## API

Documentation interactive : <http://localhost:8000/docs> (Swagger UI). Routes principales : `GET /api/health`, `/api/dashboard`, `/api/sources`
(`POST …/{clé}/test`, `POST …/{clé}/collect`), `/api/search-profiles`, `/api/offers` (filtres, tri, `PATCH …/{id}/status`, `POST /api/offers/manual`),
`/api/search-runs` (`POST` rend un identifiant, `GET …/{id}` suit l'exécution), `/api/settings/scheduler`.

## Tests et qualité

```bash
cd backend
.venv/Scripts/python -m pytest -q                         # 249 tests, SQLite temporaire, aucun accès Internet (1 à 3 min)
.venv/Scripts/python -m pytest -m network -q              # contrôle en direct des 10 sources (1 requête chacune)
.venv/Scripts/python -m ruff check .

# Même suite sur PostgreSQL (base DÉDIÉE aux tests : son schéma est recréé à chaque test)
docker exec <conteneur-db> psql -U jobart -d postgres -c "CREATE DATABASE jobart_test"
TEST_DATABASE_URL=postgresql+psycopg://jobart:<mot-de-passe>@127.0.0.1:54330/jobart_test .venv/Scripts/python -m pytest -q

cd ../frontend
npm run typecheck && npm run lint && npm test && npm run build
```

La page « Sources » de la documentation est régénérée par `backend/.venv/Scripts/python scripts/gen_source_feasibility.py` (option `--check` pour détecter un fichier périmé).

## Structure du dépôt

```
backend/        API FastAPI, moteur de collecte, connecteurs, veille, migrations Alembic, tests
frontend/       Interface Next.js (App Router, TypeScript, Tailwind, shadcn/ui)
config/         Registre des sources, employeurs, profils par défaut (YAML)
docs/           Architecture, faisabilité des sources, plan de développement
scripts/        Génération de docs/source-feasibility.md
docker-compose.yml   db + backend + frontend (+ worker en option)
```

## Limites connues et points de vigilance

- **Conditions d'utilisation** : Emploi Dakar interdit l'extraction de sa base en dehors d'un « usage personnel et privé ». Le connecteur est implémenté
  (débit réduit) pour cet usage ; **à valider** ou à désactiver (page Sources). Ce n'est pas un avis juridique ; voir `config/sources.yaml` pour les conditions de chaque source.
- **Dépôt public** : `backend/tests/fixtures/` contient des extraits tronqués de pages publiques tierces. À garder, anonymiser ou retirer selon votre choix.
- **Dates** : plusieurs sources ne publient aucune date (Remote4Africa, Wave…) : l'interface affiche « Date inconnue » et la fraîcheur n'est pas calculée.
- **Offres ouvertes ?** Une offre « visible à la dernière collecte » n'est pas garantie ouverte : vérifiez sur le site d'origine.
- **Veille** : testée (bail, rattrapage, état réel) mais pas observée sur plusieurs jours réels ; quelques sources imposent un intervalle minimal entre deux collectes.
- Couverture : 10 sources, centrées sur l'informatique et le Sénégal ; ce n'est pas une couverture exhaustive du marché.
- Pas d'authentification ni de multi-utilisateur ; pas de tests automatisés de bout en bout du navigateur.
- `npm audit` signale des vulnérabilités dans des dépendances de **développement** (`eslint-config-next`) ; elles ne sont pas incluses dans l'image de production.
