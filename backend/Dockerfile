# JobRadar - image backend (API FastAPI + worker de veille).
# Contexte de build : la RACINE du dépôt (le backend lit ../config/*.yaml) :
#   docker compose build backend        ou      docker build -f backend/Dockerfile .
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend

# Utilisateur non privilégié : la collecte n'a besoin d'aucun droit particulier.
RUN useradd --system --create-home --uid 10001 jobradar

WORKDIR /app/backend

# Dépendances d'abord (couche mise en cache tant que requirements.lock ne change pas).
# Versions verrouillées : régénérer avec `uv pip compile pyproject.toml --universal --python-version 3.14 -o requirements.lock`.
COPY backend/requirements.lock ./
RUN pip install -r requirements.lock

COPY backend/pyproject.toml backend/alembic.ini backend/docker-entrypoint.sh ./
COPY backend/alembic ./alembic
COPY backend/jobradar ./jobradar
# config/ : sources, employeurs, profils par défaut (REPO_ROOT = /app dans l'image).
COPY config /app/config

RUN chmod +x docker-entrypoint.sh && chown -R jobradar:jobradar /app
USER jobradar

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
# Par défaut : migrations puis API. Pour le worker de veille : command: ["python", "-m", "jobradar.jobs.worker"]
CMD ["uvicorn", "jobradar.main:app", "--host", "0.0.0.0", "--port", "8000"]
