.PHONY: run migrate poll install

run:
	.venv/bin/uvicorn app.main:app --reload

migrate:
	set -a && source .env && set +a && .venv/bin/alembic upgrade head

poll:
	set -a && source .env && set +a && .venv/bin/python -m app.tasks.poll_and_settle

install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
