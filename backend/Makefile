COMPOSE := docker compose -f compose.yaml

.PHONY: help infra migrate seed-demo workers demo serve api test coverage lint check down logs

help:
	@printf "make infra       Levanta PostgreSQL y Redis\n"
	@printf "make migrate     Aplica todas las ramas Alembic\n"
	@printf "make seed-demo   Inserta/reconcilia fixtures demo de Inventory\n"
	@printf "make demo        Infra + migraciones + fixtures + workers/Beat\n"
	@printf "make serve       Inicia FastAPI (requiere demo ya preparado)\n"
	@printf "make test        Ejecuta pytest\n"
	@printf "make coverage    Ejecuta pytest y exige al menos 80%% de cobertura de líneas\n"
	@printf "make check       Ruff + pytest con cobertura\n"
	@printf "make down        Detiene servicios sin borrar el volumen de PostgreSQL\n"

infra:
	$(COMPOSE) up -d --wait postgres redis

migrate: infra
	uv run alembic upgrade heads

seed-demo: migrate
	uv run python scripts/seed_demo_flights.py

workers: infra
	$(COMPOSE) up -d --build inventory-worker inventory-beat reservations-worker reservations-beat

demo:
	$(MAKE) seed-demo
	$(MAKE) workers

serve:
	uv run uvicorn flight_booking.main:app --reload --no-access-log

api: demo
	$(MAKE) serve

test:
	uv run pytest

coverage:
	uv run pytest --cov=flight_booking --cov-fail-under=80 --cov-precision=2 --cov-report=term-missing --cov-report=html

lint:
	uv run ruff check src tests scripts migrations

check: lint coverage

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f
