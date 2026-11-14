# Run from the repo root, with the backend's packages installed (pip install -e ".[dev]").
#
# The database is DATABASE_URL when it is set, else the local Docker database
# described by backend/.env (docker compose up).

-include backend/.env
DATABASE_URL ?= postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(or $(POSTGRES_PORT),5433)/$(POSTGRES_DB)
export DATABASE_URL

.PHONY: migrate

# Applies every migration the database does not have yet (backend/app/db/migrations/).
migrate:
	alembic upgrade head
