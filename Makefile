# =============================================================================
# Thin wrapper over docker compose.
#
# It earns its place for one reason: the development stack is two -f flags
# (`-f compose.yaml -f compose.dev.yaml`) and getting them wrong silently runs
# the production file instead. Everything else here is a shortcut that would
# otherwise be a paragraph in a README nobody reads at 2am.
# =============================================================================

# pipefail: `backup` and `restore` are pipelines (pg_dump | gzip | gpg, and
# gpg | gunzip | psql). Without it a pipeline exits with its LAST command's status,
# so a failed pg_dump left an "encrypted" empty file and a success, and a restore
# with the wrong passphrase exited 0 having restored nothing.
SHELL       := bash
.SHELLFLAGS := -o pipefail -c

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
.PHONY: help env preflight doctor up dev down logs ps config build-app shell psql backup backup-plaintext restore prune check-isolation

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: .env  ## Create .env from .env.example if it is missing
.env:
	@cp .env.example .env
	@echo ".env created from .env.example. It is deliberately incomplete:"
	@echo "  POSTGRES_PASSWORD      empty  -> openssl rand -base64 32"; \
	 echo "  APP_POSTGRES_PASSWORD  empty  -> a DIFFERENT openssl rand -base64 32"
	@echo "  IDENTITY_ID_SOURCE  empty  -> set to your SSO front door's header"
	@echo "`make up` will tell you what is still missing. For a laptop, `make dev`."

preflight:  ## Check .env for settings that would deploy insecurely
	@python3 scripts/preflight.py

# preflight reads .env and nothing else, so it cannot see the one failure .env
# causes and cannot explain: Postgres applies POSTGRES_PASSWORD only when it
# initializes an empty volume, so changing it later leaves the database on the
# old one. This asks the running database what it actually accepts.
doctor:  ## Diagnose a stack that is up but not working
	@python3 scripts/doctor.py

build-app:  ## Rebuild docs/app/index.html from app/ (runs on the host, not in Docker)
	pixi run build-app

up: env preflight  ## Production-shaped stack: no exposed API, no exposed database
	$(COMPOSE) up -d
	@echo "Dashboard: http://localhost:$(HTTP_PORT)/"

# POSTGRES_PASSWORD is supplied here rather than left to .env. The base file
# guards it with `${VAR:?...}`, and compose resolves that during interpolation
# of compose.yaml -- BEFORE compose.dev.yaml's default can override it. So an
# empty password in .env (which is what the template ships, on purpose) stops
# `make dev` too, for a stack that has no business needing a real one. Read the
# .env value if there is one, fall back to the dev-only string otherwise.
dev: env  ## Development stack: fixed dev identity, hot reload, exposed ports
	@PW="$$(sed -n 's/^POSTGRES_PASSWORD=//p' .env | tr -d '\"'\''')"; \
	 ID="$$(sed -n 's/^DEV_IDENTITY_ID=//p' .env | tr -d '\"'\''')"; \
	 POSTGRES_PASSWORD="$${PW:-dev-only-not-a-secret}" \
	 IDENTITY_ID_SOURCE="$${ID:-dev@localhost}" \
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

# Encrypted, because the dump is every governance record, every audit entry
# and every retained version in one file. BACKUP_PASSPHRASE is required: a
# plaintext dump sitting in the working directory is 164.310(d)(2)(i) waiting
# to happen, and making encryption opt-in means it is off.
#
# Uses gpg --symmetric, which is present on far more machines than age. Set
# BACKUP_RETAIN to prune older dumps (default: keep everything).
#
# The passphrase is read from the ENVIRONMENT as $$BACKUP_PASSPHRASE, never
# expanded as $(BACKUP_PASSPHRASE): make pastes an expanded variable into the
# recipe text, which is then the argv of `sh -c`, readable by every local
# account. scripts/backup_crypto.sh hands it to gpg through a mode-600 file.
# Export it; do not write `make backup BACKUP_PASSPHRASE=...` (that is make's argv).
backup:  ## Encrypted pg_dump to backups/<timestamp>.sql.gz.gpg
	@test -n "$$BACKUP_PASSPHRASE" || { \
	  echo "BACKUP_PASSPHRASE is not set."; \
	  echo; \
	  echo "  The dump contains every record, audit entry and retained"; \
	  echo "  version. Writing it in the clear is not a backup policy."; \
	  echo; \
	  echo "  Generate one and keep it somewhere other than this machine:"; \
	  echo "    export BACKUP_PASSPHRASE=\"\$$(openssl rand -base64 32)\""; \
	  echo; \
	  echo "  make backup-plaintext PLAINTEXT=1   # dev databases only"; \
	  exit 1; }
	@mkdir -p $(BACKUP_DIR) && chmod 700 $(BACKUP_DIR)
	@OUT=$(BACKUP_DIR)/$$(date -u +%Y%m%dT%H%M%SZ).sql.gz.gpg; \
	 $(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists \
	   | gzip \
	   | scripts/backup_crypto.sh encrypt "$$OUT" \
	 && chmod 600 "$$OUT" && ls -lh "$$OUT" \
	 || { rm -f "$$OUT"; echo "backup FAILED: no file was kept" >&2; exit 1; }
	@if [ -n "$(BACKUP_RETAIN)" ]; then \
	  ls -1t $(BACKUP_DIR)/*.sql.gz.gpg 2>/dev/null | tail -n +$$(($(BACKUP_RETAIN)+1)) \
	    | xargs -r rm -v; \
	fi
	@echo "Dumped through the running server. Do NOT back this up by copying the volume's files -- a live cluster gives you a torn snapshot."
	@echo "Keep the passphrase somewhere other than this machine. Without it this file is unrecoverable."

backup-plaintext:  ## UNENCRYPTED pg_dump. Throwaway databases only.
	@test -n "$(PLAINTEXT)" || { echo "refusing: pass PLAINTEXT=1 to confirm"; exit 1; }
	@mkdir -p $(BACKUP_DIR) && chmod 700 $(BACKUP_DIR)
	$(COMPOSE) exec -T $(DB_SERVICE) pg_dump -U $(POSTGRES_USER) -d $(POSTGRES_DB) --clean --if-exists \
	  | gzip > $(BACKUP_DIR)/$$(date -u +%Y%m%dT%H%M%SZ).sql.gz
	@echo "UNENCRYPTED dump written. Do not do this with real records."

# Handles both shapes, so an older plaintext dump still restores.
restore:  ## Restore a dump: make restore FILE=backups/....sql.gz.gpg  (DESTRUCTIVE)
	@test -n "$(FILE)" || { echo "usage: make restore FILE=backups/<file>.sql.gz.gpg"; exit 1; }
	@case "$(FILE)" in \
	  *.gpg) test -n "$$BACKUP_PASSPHRASE" || { echo "BACKUP_PASSPHRASE is needed to read $(FILE)" >&2; exit 1; }; \
	         scripts/backup_crypto.sh decrypt "$(FILE)" ;; \
	  *)     cat "$(FILE)" ;; \
	esac | gunzip -c | $(COMPOSE) exec -T $(DB_SERVICE) psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

# The logic is scripts/check_isolation.py, so it can be tested and so it exits
# non-zero on a failure. It used to be shell that printed what it found and ended
# step 3 with `|| true` (#56).
check-isolation:  ## Prove the API is not reachable except through the proxy
	@HTTP_PORT=$(HTTP_PORT) python3 scripts/check_isolation.py

prune:  ## Remove containers AND the database volume. Destroys all data.
	@printf 'This deletes the pgdata volume permanently. Type YES to continue: ' \
	  && read ans && [ "$$ans" = YES ] || { echo aborted; exit 1; }
	$(COMPOSE) down -v
