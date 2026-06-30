.PHONY: run migrate migrate-prod poll sync odds resettle resettle-all wipe-data install

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

odds:
	set -a && source .env && set +a && .venv/bin/python -c "import asyncio; from app.tasks.poll_and_settle import sync_odds; asyncio.run(sync_odds())"

resettle:
	@test -n "$(GROUP_ID)" || (echo "Usage: make resettle GROUP_ID=<id>" && exit 1)
	set -a && source .env && set +a && .venv/bin/python -m app.tasks.resettle $(GROUP_ID)

resettle-all:
	set -a && source .env && set +a && .venv/bin/python -m app.tasks.resettle --all

wipe-data:
	@test -n "$(WIPE_URL)" || (echo "Usage: make wipe-data WIPE_URL=<database_url>" && exit 1)
	.venv/bin/python -m app.tasks.wipe_data "$(WIPE_URL)"

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
