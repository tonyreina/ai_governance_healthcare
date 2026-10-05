# =============================================================================
# Thin wrapper over docker compose.
#
# It earns its place for one reason: the development stack is two -f flags
# (`-f compose.yaml -f compose.dev.yaml`) and getting them wrong silently runs
# the production file instead. Everything else here is a shortcut that would
# otherwise be a paragraph in a README nobody reads at 2am.
# =============================================================================

COMPOSE     := docker compose
DEV         := $(COMPOSE) -f compose.yaml -f compose.dev.yaml
DB_SERVICE  := db
BACKUP_DIR  := backups

# .env is read by compose automatically; these mirror its defaults so the
# backup and psql targets work without sourcing it.
POSTGRES_USER ?= chai
POSTGRES_DB   ?= chai
HTTP_PORT     ?= 8080

.DEFAULT_GOAL := help
.PHONY: help env up dev down logs ps config build-app shell psql backup restore prune check-isolation

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: .env  ## Create .env from .env.example if it is missing
.env:
	@cp .env.example .env
	@echo ".env created from .env.example -- edit POSTGRES_PASSWORD before deploying."

build-app:  ## Rebuild docs/app/index.html from app/ (runs on the host, not in Docker)
	pixi run build-app

up: env  ## Production-shaped stack: no exposed API, no exposed database
	$(COMPOSE) up -d
	@echo "Dashboard: http://localhost:$(HTTP_PORT)/"

dev: env  ## Development stack: fixed dev identity, hot reload, exposed ports
	$(DEV) up

down:  ## Stop and remove containers. The pgdata volume SURVIVES this.
	$(COMPOSE) down

logs:  ## Follow logs for all services
	$(COMPOSE) logs -f --tail=100

ps:  ## Show service status and health
	$(COMPOSE) ps

config:  ## Render the merged production config (what actually runs)
	$(COMPOSE) config

shell:  ## Shell in the API container
	$(COMPOSE) exec api sh

psql:  ## Interactive psql inside the database container
	$(COMPOSE) exec $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

backup:  ## pg_dump to backups/<timestamp>.sql.gz
	@mkdir -p $(BACKUP_DIR)
	$(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists \
	  | gzip > $(BACKUP_DIR)/$$(date -u +%Y%m%dT%H%M%SZ).sql.gz
	@ls -lh $(BACKUP_DIR) | tail -1
	@echo "Dumped through the running server. Do NOT back this up by copying the volume's files -- a live cluster gives you a torn snapshot."

restore:  ## Restore a dump: make restore FILE=backups/....sql.gz  (DESTRUCTIVE)
	@test -n "$(FILE)" || { echo "usage: make restore FILE=backups/<file>.sql.gz"; exit 1; }
	gunzip -c $(FILE) | $(COMPOSE) exec -T $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

check-isolation:  ## Prove the API is not reachable except through the proxy
	@echo "1. no published port on api or db:"
	@$(COMPOSE) ps --format '  {{.Service}}  ports=[{{.Publishers}}]'
	@echo "2. direct connection to the API from the host (MUST fail):"
	@! curl -sS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1 \
	  && echo "  refused -- correct" \
	  || { echo "  REACHABLE -- the identity header can be forged. Check for a ports: entry on api."; exit 1; }
	@echo "3. forged identity through the proxy (MUST be stripped):"
	@curl -sS --max-time 5 -H 'X-Auth-Request-User: attacker@evil.test' \
	  http://127.0.0.1:$(HTTP_PORT)/api/me || true

prune:  ## Remove containers AND the database volume. Destroys all data.
	@printf 'This deletes the pgdata volume permanently. Type YES to continue: ' \
	  && read ans && [ "$$ans" = YES ] || { echo aborted; exit 1; }
	$(COMPOSE) down -v
