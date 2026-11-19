import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from flight_booking.api.access_log import AccessLogMiddleware
from flight_booking.api.v1.router import router as v1_router
from flight_booking.modules.inventory.adapters.persistence.session import engine
from flight_booking.modules.payments.adapters.persistence.session import (
    engine as payments_engine,
)
from flight_booking.modules.reservations.adapters.http.realtime import (
    run_stream_delivery,
)
from flight_booking.modules.reservations.adapters.persistence.session import (
    engine as reservations_engine,
)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stream_task = asyncio.create_task(run_stream_delivery())
        try:
            yield
        finally:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass
            await engine.dispose()
            await reservations_engine.dispose()
            await payments_engine.dispose()

    app = FastAPI(
        title="Flight Booking API",
        version="1.0.0",
        description="API versionada para el sistema de reservas de vuelos.",
        lifespan=lifespan,
    )
    app.include_router(v1_router, prefix="/api/v1")
    app.add_middleware(AccessLogMiddleware)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
