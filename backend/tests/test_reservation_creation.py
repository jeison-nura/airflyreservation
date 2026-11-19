import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_booking.main import app
from flight_booking.modules.payments.adapters.commands import SqlAlchemyPaymentCommands
from flight_booking.modules.payments.adapters.persistence.models import (
    Base as PaymentBase,
)
from flight_booking.modules.reservations.adapters.http.router import (
    get_confirm_reservation,
    get_create_reservation,
    get_reservation_repository,
)
from flight_booking.modules.reservations.adapters.persistence.models import Base
from flight_booking.modules.reservations.adapters.persistence.repository import (
    SqlAlchemyReservationRepository,
)
from flight_booking.modules.reservations.application.confirm_reservation import (
    ConfirmReservation,
)
from flight_booking.modules.reservations.application.create_reservation import (
    CreateReservation,
    SeatUnavailable,
)
from flight_booking.modules.reservations.application.expire_reservations import (
    ExpireReservations,
)
from flight_booking.modules.reservations.application.ports import (
    FlightQuote,
    IdempotencyKeyConflict,
    PaymentResult,
)

NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


class FixedClock:
    def now(self):
        return NOW


class FakeInventory:
    def __init__(self, *, unavailable=False):
        self.holds = []
        self.unavailable = unavailable

    async def hold(
        self, flight_id, seat_number, reservation_id, expires_at, *, correlation_id
    ):
        self.holds.append((flight_id, seat_number, reservation_id, expires_at))
        if self.unavailable:
            raise SeatUnavailable

    async def confirm(
        self, flight_id, seat_number, reservation_id, *, correlation_id
    ):
        self.confirmed = (flight_id, seat_number, reservation_id)
        self.confirm_count = getattr(self, "confirm_count", 0) + 1

    async def release(
        self, flight_id, seat_number, reservation_id, *, correlation_id
    ):
        self.released = (flight_id, seat_number, reservation_id)


class FakePricing:
    async def quote(self, _flight_id):
        return FlightQuote(Decimal(189900), "COP")


class FakePayments:
    def __init__(self, authorize_status="AUTHORIZED", capture_status="CAPTURED"):
        self.authorize_status = authorize_status
        self.capture_status = capture_status
        self.attempt_ref = None
        self.authorize_count = 0
        self.capture_count = 0

    async def authorize(self, *, payment_attempt_ref, **_kwargs):
        self.authorize_count += 1
        self.attempt_ref = payment_attempt_ref
        return PaymentResult(self.authorize_status, payment_attempt_ref)

    async def capture(self, *, payment_attempt_ref, **_kwargs):
        self.capture_count += 1
        return PaymentResult(self.capture_status, payment_attempt_ref)

    async def query_attempt(self, *, payment_attempt_ref, **_kwargs):
        return PaymentResult(self.authorize_status, payment_attempt_ref)

    async def void(self, *, payment_attempt_ref, **_kwargs):
        return PaymentResult("VOIDED", payment_attempt_ref)

    async def refund(self, *, payment_attempt_ref, **_kwargs):
        return PaymentResult("REFUNDED", payment_attempt_ref)


def test_create_reservation_holds_seat_and_replay_does_not_reissue_token():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        insert_statements = []

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def capture_inserts(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("INSERT INTO RESERVATIONS."):
                insert_statements.append(statement)

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            inventory = FakeInventory()
            use_case = CreateReservation(
                repository, inventory, FakePricing(), FixedClock()
            )

            created = await use_case.execute(
                flight_id="flight-204",
                seat_number="4A",
                full_name="Ada Lovelace",
                email="ada@example.test",
                idempotency_key="client-request-001",
            )
            assert created.access_token
            assert created.replayed is False
            assert created.aggregate.reservation.expires_at == NOW + timedelta(
                minutes=10
            )
            assert created.aggregate.saga.step.value == "HOLD_OBTAINED"
            assert len(inventory.holds) == 1
            reservation_insert = next(
                index
                for index, statement in enumerate(insert_statements)
                if "INSERT INTO RESERVATIONS.RESERVATIONS" in statement.upper()
            )
            passenger_insert = next(
                index
                for index, statement in enumerate(insert_statements)
                if "INSERT INTO RESERVATIONS.PASSENGER_DETAILS" in statement.upper()
            )
            assert reservation_insert < passenger_insert

            replayed = await use_case.execute(
                flight_id="flight-204",
                seat_number="4A",
                full_name="Ada Lovelace",
                email="ada@example.test",
                idempotency_key="client-request-001",
            )
            assert replayed.replayed is True
            assert replayed.access_token is None
            assert replayed.aggregate.reservation.id == created.aggregate.reservation.id
            assert len(inventory.holds) == 1

            with pytest.raises(IdempotencyKeyConflict):
                await use_case.execute(
                    flight_id="flight-204",
                    seat_number="4B",
                    full_name="Ada Lovelace",
                    email="ada@example.test",
                    idempotency_key="client-request-001",
                )
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_failed_hold_marks_reservation_failed():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            inventory = FakeInventory(unavailable=True)
            use_case = CreateReservation(
                repository, inventory, FakePricing(), FixedClock()
            )
            with pytest.raises(SeatUnavailable):
                await use_case.execute(
                    flight_id="flight-204",
                    seat_number="4A",
                    full_name="Ada Lovelace",
                    email="ada@example.test",
                    idempotency_key="client-request-002",
                )
            aggregate = await repository.get(inventory.holds[0][2])
            assert aggregate is not None
            assert aggregate.reservation.status.value == "FAILED"
            assert aggregate.saga.step.value == "DONE"
            # The idempotency row still points to the terminal outcome; replay cannot
            # silently allocate a new seat or mint a new credential.
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_reservations_http_create_replay_and_capability_protected_read(capsys):
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")
            connection.execute("ATTACH DATABASE ':memory:' AS payments")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.run_sync(PaymentBase.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            repository = SqlAlchemyReservationRepository(sessions)
            app.dependency_overrides[get_reservation_repository] = lambda: repository
            app.dependency_overrides[get_create_reservation] = lambda: CreateReservation(
                repository, FakeInventory(), FakePricing(), FixedClock()
            )
            app.dependency_overrides[get_confirm_reservation] = lambda: ConfirmReservation(
                repository, FakeInventory(), SqlAlchemyPaymentCommands(sessions), FixedClock()
            )

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                payload = {
                    "flightId": "flight-204",
                    "seatNumber": "4A",
                    "passenger": {
                        "fullName": "Ada Lovelace",
                        "email": "ada@example.test",
                    },
                }
                headers = {"Idempotency-Key": "http-request-001"}
                created = await client.post(
                    "/api/v1/reservations", json=payload, headers=headers
                )
                assert created.status_code == 201
                created_data = created.json()
                assert created_data["status"] == "PENDING"
                assert created_data["accessToken"]

                replay = await client.post(
                    "/api/v1/reservations", json=payload, headers=headers
                )
                assert replay.status_code == 200
                assert replay.json()["replayed"] is True
                assert "accessToken" not in replay.json()
                assert replay.json()["accessCredentialAvailable"] is False

                reservation_url = (
                    f"/api/v1/reservations/{created_data['reservationId']}"
                )
                unauthorized = await client.get(reservation_url)
                assert unauthorized.status_code == 401
                authorized = await client.get(
                    reservation_url,
                    headers={
                        "Authorization": f"Bearer {created_data['accessToken']}"
                    },
                )
                assert authorized.status_code == 200
                assert authorized.json()["status"] == "PENDING"
                notifications = await client.get(
                    f"{reservation_url}/events?after=0",
                    headers={
                        "Authorization": f"Bearer {created_data['accessToken']}"
                    },
                )
                assert notifications.status_code == 200
                assert notifications.json()["events"][0]["sequence"] == 1
                assert notifications.json()["events"][0]["status"] == "PENDING"

                confirmed = await client.post(
                    f"{reservation_url}/confirm",
                    headers={
                        "Authorization": f"Bearer {created_data['accessToken']}",
                        "Idempotency-Key": "http-confirm-001",
                    },
                )
                assert confirmed.status_code == 200
                assert confirmed.json()["status"] == "CONFIRMED"
                assert confirmed.json()["bookingCode"]

                output = capsys.readouterr().out
                records = [json.loads(line) for line in output.splitlines()]
                created_log = next(r for r in records if r["event"] == "reservation_created")
                confirmed_log = next(
                    r for r in records
                    if r["event"] == "reservation_saga_transition" and r["status"] == "CONFIRMED"
                )
                assert created_log["request_id"] == created.headers["X-Request-ID"]
                assert confirmed_log["request_id"] == confirmed.headers["X-Request-ID"]
                assert created_log["request_id"] != confirmed_log["request_id"]
                assert confirmed_log["correlation_id"] == created_log["correlation_id"]
                assert created_log["correlation_id"] == created_data["correlationId"]
                payment_logs = [r for r in records if r["module"] == "payments"]
                assert [r["outcome"] for r in payment_logs] == ["AUTHORIZED", "CAPTURED"]
                assert all(
                    r["request_id"] == confirmed_log["request_id"]
                    and r["correlation_id"] == confirmed_log["correlation_id"]
                    for r in payment_logs
                )
                for private in (
                    "Ada Lovelace", "ada@example.test", "http-confirm-001",
                    created_data["accessToken"], confirmed.json()["bookingCode"],
                ):
                    assert private not in output
        finally:
            app.dependency_overrides.clear()
            await engine.dispose()

    asyncio.run(exercise())


def test_reservation_expiration_releases_held_seat_and_resumes_saga():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            inventory = FakeInventory()
            created = await CreateReservation(
                repository, inventory, FakePricing(), FixedClock()
            ).execute(
                flight_id="flight-204",
                seat_number="4A",
                full_name="Ada Lovelace",
                email="ada@example.test",
                idempotency_key="expire-request-001",
            )
            later = NOW + timedelta(minutes=10)

            class LaterClock:
                def now(self):
                    return later

            result = await ExpireReservations(
                repository, inventory, LaterClock()
            ).run_once()
            expired = await repository.get(created.aggregate.reservation.id)
            assert result.expired == 1
            assert result.compensation_resolved == 1
            assert expired is not None
            assert expired.reservation.status.value == "EXPIRED"
            assert expired.saga.step.value == "DONE"
            assert inventory.released == ("flight-204", "4A", expired.reservation.id)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_purchase_saga_authorizes_books_captures_and_confirms():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            inventory, payments = FakeInventory(), FakePayments()
            created = await CreateReservation(
                repository, inventory, FakePricing(), FixedClock()
            ).execute(
                flight_id="flight-204",
                seat_number="4A",
                full_name="Ada Lovelace",
                email="ada@example.test",
                idempotency_key="confirm-create-001",
            )
            result = await ConfirmReservation(
                repository, inventory, payments, FixedClock()
            ).execute(
                created.aggregate.reservation.id,
                idempotency_key="confirm-request-001",
            )
            assert result.pending is False
            assert result.aggregate.reservation.status.value == "CONFIRMED"
            assert result.aggregate.reservation.currency == "COP"
            assert result.aggregate.reservation.amount == Decimal(189900)
            assert result.aggregate.reservation.booking_code
            assert result.aggregate.saga.step.value == "DONE"
            assert inventory.confirmed[2] == created.aggregate.reservation.id
            replay = await ConfirmReservation(
                repository, inventory, payments, FixedClock()
            ).execute(
                created.aggregate.reservation.id,
                idempotency_key="confirm-request-001",
            )
            assert replay.aggregate.reservation.booking_code == (
                result.aggregate.reservation.booking_code
            )
            assert payments.authorize_count == 1
            assert payments.capture_count == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_authorization_denial_releases_hold_before_marking_failed():
    async def exercise():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(engine.sync_engine, "connect")
        def attach_schema(connection, _record):
            connection.execute("ATTACH DATABASE ':memory:' AS reservations")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            repository = SqlAlchemyReservationRepository(
                async_sessionmaker(engine, expire_on_commit=False)
            )
            inventory = FakeInventory()
            created = await CreateReservation(
                repository, inventory, FakePricing(), FixedClock()
            ).execute(
                flight_id="flight-204",
                seat_number="4A",
                full_name="Ada Lovelace",
                email="ada@example.test",
                idempotency_key="denied-create-001",
            )
            result = await ConfirmReservation(
                repository,
                inventory,
                FakePayments(authorize_status="DENIED"),
                FixedClock(),
            ).execute(
                created.aggregate.reservation.id,
                idempotency_key="denied-confirm-001",
            )
            assert result.pending is False
            assert result.aggregate.reservation.status.value == "FAILED"
            assert result.aggregate.reservation.failure_reason == "PAYMENT_DENIED"
            assert result.aggregate.saga.step.value == "DONE"
            assert inventory.released[2] == created.aggregate.reservation.id
        finally:
            await engine.dispose()

    asyncio.run(exercise())
