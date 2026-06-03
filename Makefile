.PHONY: run migrate migrate-prod poll sync install

run:
	.venv/bin/uvicorn app.main:app --reload

migrate:
	set -a && source .env && set +a && .venv/bin/alembic upgrade head

migrate-prod:
	@test -n "$(PROD_DATABASE_URL)" || (echo "Usage: make migrate-prod PROD_DATABASE_URL=<url>" && exit 1)
	DATABASE_URL=$(PROD_DATABASE_URL) .venv/bin/alembic upgrade head

poll:
	set -a && source .env && set +a && .venv/bin/python -m app.tasks.poll_and_settle

sync:
	set -a && source .env && set +a && .venv/bin/python -m app.tasks.sync_fixtures_cli

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
