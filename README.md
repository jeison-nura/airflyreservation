# Sistema de reservas de vuelos en tiempo real

Prototipo de búsqueda de vuelos, selección y bloqueo temporal de asientos,
confirmación ficticia de reservas y tablero de ocupación en tiempo real.

## Tecnologías

| Área | Tecnologías |
| --- | --- |
| Frontend | React, Next.js, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI, SQLAlchemy async, Alembic, Celery |
| Persistencia | PostgreSQL, con esquema por módulo |
| Tiempo real | WebSockets y Redis Streams |
| Desarrollo local | Docker Compose, Make, `uv`, pnpm |
| Pruebas | Jest, React Testing Library, pytest, pytest-cov, Playwright MCP |

La arquitectura es un monolito modular con principios hexagonales y DDD ligero.
Inventory es dueño de vuelos/asientos; Reservations coordina la reserva y
Payments usa un adaptador ficticio. El pago no solicita tarjeta ni contacta una
pasarela real.

## Requisitos previos

- Docker Desktop o Docker Engine con plugin `docker compose`.
- GNU Make.
- Python **3.12 o superior** y `uv`.
- Node.js **22** y Corepack; pnpm **12.21.0** se invoca mediante Corepack.
- Google Chrome solo para pruebas manuales de navegador con MCP.

## Ejecutar localmente

Desde la raíz del repositorio:

```bash
make dev
```

Este comando instala dependencias, inicia PostgreSQL y Redis, aplica las
migraciones, prepara los datos demo e inicia workers, API y frontend. Abre
`http://localhost:3000`; la vista de ocupación está en
`http://localhost:3000/estadisticas`.

Para comprobar la ocupación en vivo, abre **Estadísticas** y el mapa del mismo
vuelo en otra pestaña. Al pulsar **Crear reserva**, un asiento pasa de disponible
a bloqueado; al confirmar la compra ficticia, pasa a confirmado. Si el bloqueo
vence sin confirmar, el asiento vuelve a disponible. Solo seleccionarlo no cambia
los contadores.

Para detener los servicios sin borrar el volumen de PostgreSQL:

```bash
make down
```

Comandos adicionales: `make help`, `make demo`, `make api` y `make frontend`.
La configuración de desarrollo define credenciales locales de demostración;
no las reutilices en un entorno público.

Para depurar, revisa los eventos JSON de la API en la terminal de `make dev`
y los de los workers con `make logs`. Usa `X-Request-ID` para encontrar una
llamada HTTP y `correlation_id` para seguir la misma reserva entre módulos.

## Pruebas y calidad

```bash
make check
```

Ejecuta Ruff, pytest con cobertura, ESLint, TypeScript y Jest con cobertura.
Cada proyecto exige un mínimo global de **80 % de cobertura de líneas**.
También se puede ejecutar `make test` para las suites sin cobertura.

Para generar los informes por separado:

```bash
cd frontend
pnpm test:coverage
pnpm build
```

```bash
cd backend
make coverage
```

La última verificación documentada obtuvo 81,04 % de líneas en frontend (35
pruebas, 14 suites) y 82,31 % en backend (62 aprobadas, 4 integraciones
optativas omitidas). Las integraciones optativas con PostgreSQL y Redis requieren
servicios locales y sus variables `RUN_*_TESTS`; los detalles están resumidos en
`docs/architecture.md`.

### Prueba de navegador con Playwright MCP

En tu cliente MCP, habilita Playwright (`@playwright/mcp`) con un navegador
local. Inicia el proyecto con `make dev` y ejecuta el escenario
`frontend/tests/browser/booking-realtime.playwright` desde el navegador
controlado por Playwright MCP. El escenario abre clientes aislados, comprueba el
evento WebSocket, el aviso, su respaldo HTTP y los cambios del tablero. Usa
viewport de 1440 × 900 y deja una reserva ficticia confirmada en la base demo.
No es necesario instalar un MCP para ejecutar Jest o pytest.

## Documentación de entrega

- [Arquitectura, diagramas, decisiones y flujos](docs/architecture.md)
- [Uso de IA, prompts e impacto estimado](docs/ia.md)
