"""Reservations database connection; never import another module's repository."""

import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:local-dev-only@localhost:5432/flight_booking",
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, hide_parameters=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
