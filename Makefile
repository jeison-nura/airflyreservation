.PHONY: help setup demo dev api frontend backend-test frontend-test test check down logs

help:
	@printf "make setup         Instala dependencias\n"
	@printf "make demo          Levanta servicios, migra y reconcilia vuelos/asientos demo\n"
	@printf "make dev           Prepara demo y ejecuta API + frontend\n"
	@printf "make api           Prepara demo y ejecuta solo la API\n"
	@printf "make frontend      Instala y ejecuta solo el frontend\n"
	@printf "make test          Ejecuta las suites de backend y frontend\n"
	@printf "make check         Ejecuta lint, tipos y pruebas\n"
	@printf "make down          Detiene servicios sin borrar datos\n"

setup:
	cd backend && uv sync
	cd frontend && corepack pnpm install --frozen-lockfile

demo:
	$(MAKE) -C backend demo

dev:
	$(MAKE) setup
	$(MAKE) demo
	$(MAKE) -j2 backend-api frontend-dev

api:
	$(MAKE) setup
	$(MAKE) demo
	$(MAKE) -C backend serve

frontend:
	$(MAKE) setup
	$(MAKE) -C frontend dev

backend-api:
	$(MAKE) -C backend serve

frontend-dev:
	$(MAKE) -C frontend dev

backend-test:
	$(MAKE) -C backend test

frontend-test:
	$(MAKE) -C frontend test

test:
	$(MAKE) -j2 backend-test frontend-test

check:
	$(MAKE) -j2 -C backend check
	$(MAKE) -C frontend check

down:
	$(MAKE) -C backend down

logs:
	$(MAKE) -C backend logs
