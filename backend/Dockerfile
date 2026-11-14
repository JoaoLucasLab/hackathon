# Backend image (FastAPI + OR-Tools). Build context is the REPO ROOT, because the
# app needs pyproject.toml and fixtures/:
#   docker build -f backend/Dockerfile -t course-planner-backend .
# Used by the WSL backup host (deploy/wsl/compose.yaml). It also runs on Render's
# Docker runtime: it listens on $PORT (Render sets it; default 8000).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Editable install keeps REPO_ROOT (app/config.py) at /app, so fixtures/ resolves
# the same way as in local dev.
COPY pyproject.toml ./
COPY backend ./backend
COPY fixtures ./fixtures
RUN pip install -e . \
    && useradd --create-home --uid 10001 app \
    && chown -R app /app

USER app
EXPOSE 8000

# Until DATA-01 adds GET /health, /openapi.json proves the app started.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/openapi.json', timeout=4)"

# --proxy-headers: TLS ends at Tailscale Funnel / Render, so trust X-Forwarded-Proto
# for correct https URLs and Secure cookies.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
