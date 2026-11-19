.PHONY: help install dev build lint typecheck test coverage check

help:
	@printf "make install    Instala dependencias con el lockfile\n"
	@printf "make dev        Inicia Next.js en modo desarrollo\n"
	@printf "make coverage   Ejecuta Jest y exige al menos 80%% de cobertura de líneas\n"
	@printf "make check      Lint + TypeScript + Jest con cobertura\n"

install:
	corepack pnpm install --frozen-lockfile

dev:
	corepack pnpm dev

build:
	corepack pnpm build

lint:
	corepack pnpm lint

typecheck:
	corepack pnpm typecheck

test:
	corepack pnpm test

coverage:
	corepack pnpm test:coverage

check: lint typecheck coverage
