import asyncio
import json
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.modules.payments.adapters.commands import SqlAlchemyPaymentCommands
from flight_booking.modules.payments.adapters.persistence.models import Base
from flight_booking.modules.payments.domain.models import PaymentConflict


def test_fake_payments_authorize_capture_refund_and_idempotent_replay(capsys):
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS payments")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            commands = SqlAlchemyPaymentCommands(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            args = {
                "payment_attempt_ref": "attempt-123",
                "reservation_id": "reservation-123",
                "amount": Decimal(189900),
                "currency": "COP",
                "idempotency_key": "reservation-123-authorize",
                "correlation_id": "a" * 32,
            }
            authorized = await commands.authorize(**args)
            replay = await commands.authorize(**args)
            assert authorized.status == replay.status == "AUTHORIZED"

            capture_args = {
                "payment_attempt_ref": "attempt-123",
                "idempotency_key": "reservation-123-capture",
                "correlation_id": "a" * 32,
            }
            captured = await commands.capture(**capture_args)
            capture_replay = await commands.capture(**capture_args)
            assert captured.status == capture_replay.status == "CAPTURED"

            refunded = await commands.refund(
                payment_attempt_ref="attempt-123",
                idempotency_key="reservation-123-refund",
                correlation_id="a" * 32,
            )
            assert refunded.status == "REFUNDED"
            assert (
                await commands.query_attempt(
                    payment_attempt_ref="attempt-123",
                    correlation_id="a" * 32,
                )
            ).status == "REFUNDED"

            with pytest.raises(PaymentConflict):
                await commands.capture(
                    payment_attempt_ref="attempt-123",
                    idempotency_key="different-capture-key",
                    correlation_id="a" * 32,
                )
        finally:
            await engine.dispose()

    asyncio.run(exercise())
    output = capsys.readouterr().out
    records = [json.loads(line) for line in output.splitlines()]
    operations = {
        (record["operation"], record["outcome"]) for record in records
        if record["module"] == "payments"
    }
    assert {
        ("authorize", "AUTHORIZED"), ("capture", "CAPTURED"),
        ("refund", "REFUNDED"), ("capture", "conflict"),
    } <= operations
    assert all(record["correlation_id"] == "a" * 32 for record in records)
    assert "different-capture-key" not in output
    assert "189900" not in output
    assert "attempt-123" not in output


def test_fake_payments_voids_authorization_and_reports_unknown_attempt():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS payments")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            commands = SqlAlchemyPaymentCommands(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            await commands.authorize(
                payment_attempt_ref="attempt-void",
                reservation_id="reservation-void",
                amount=Decimal("10.00"),
                currency="USD",
                idempotency_key="void-authorize-key",
                correlation_id="correlation-void",
            )
            voided = await commands.void(
                payment_attempt_ref="attempt-void",
                idempotency_key="void-operation-key",
                correlation_id="correlation-void",
            )
            unknown = await commands.query_attempt(
                payment_attempt_ref="does-not-exist",
                correlation_id="correlation-void",
            )
            assert voided.status == "VOIDED"
            assert unknown.status == "UNKNOWN"
        finally:
            await engine.dispose()

    asyncio.run(exercise())
