.PHONY: dev migrate seed poll-once test up down logs

dev:
	docker compose up --build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f app

migrate:
	docker compose run --rm app alembic upgrade head

seed:
	docker compose run --rm app python -m scripts.seed

poll-once:
	docker compose run --rm app python -m poller.once --cargo 1 --abrangencia BR

sync-candidatos:
	docker compose run --rm app python -m poller.candidatos_tse

test:
	python -m pytest tests/ -v
