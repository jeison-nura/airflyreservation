"""Create normalized Inventory catalog, flights, and per-flight seats.

Revision ID: 01a1f1807fbb7f1b93c235d8438ae314
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "01a1f1807fbb7f1b93c235d8438ae314"
down_revision = None
branch_labels = ("inventory",)
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS inventory")

    op.create_table(
        "cities",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "country_code", name="uq_cities_name_country"),
        schema="inventory",
    )
    op.create_table(
        "airlines",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        schema="inventory",
    )
    op.create_table(
        "currencies",
        sa.Column("code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("minor_unit", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("length(code) = 3", name="ck_currencies_code_length"),
        sa.CheckConstraint("minor_unit BETWEEN 0 AND 4", name="ck_currencies_minor_unit"),
        sa.PrimaryKeyConstraint("code"),
        schema="inventory",
    )
    op.create_table(
        "airports",
        sa.Column("iata_code", sa.String(length=3), nullable=False),
        sa.Column("city_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.CheckConstraint("length(iata_code) = 3", name="ck_airports_iata_code_length"),
        sa.ForeignKeyConstraint(["city_id"], ["inventory.cities.id"]),
        sa.PrimaryKeyConstraint("iata_code"),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_airports_city_id",
        "airports",
        ["city_id"],
        schema="inventory",
    )
    op.create_table(
        "flights",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("airline_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("flight_number", sa.String(length=32), nullable=False),
        sa.Column("origin_airport_code", sa.String(length=3), nullable=False),
        sa.Column("destination_airport_code", sa.String(length=3), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("origin_time", sa.Time(), nullable=False),
        sa.Column("destination_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_minor_units", sa.BigInteger(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "origin_airport_code <> destination_airport_code",
            name="ck_flights_distinct_airports",
        ),
        sa.CheckConstraint("price_minor_units >= 0", name="ck_flights_nonnegative_price"),
        sa.CheckConstraint("duration_minutes >= 0", name="ck_flights_nonnegative_duration"),
        sa.CheckConstraint(
            "status IN ('ON_TIME', 'DELAYED', 'CANCELLED')",
            name="ck_flights_status",
        ),
        sa.ForeignKeyConstraint(["airline_id"], ["inventory.airlines.id"]),
        sa.ForeignKeyConstraint(
            ["origin_airport_code"],
            ["inventory.airports.iata_code"],
        ),
        sa.ForeignKeyConstraint(
            ["destination_airport_code"],
            ["inventory.airports.iata_code"],
        ),
        sa.ForeignKeyConstraint(["currency_code"], ["inventory.currencies.code"]),
        sa.PrimaryKeyConstraint("id"),
        schema="inventory",
    )
    op.create_index(
        "ix_flights_route_departure",
        "flights",
        ["origin_airport_code", "destination_airport_code", "departure_date"],
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_flights_airline_id",
        "flights",
        ["airline_id"],
        schema="inventory",
    )
    op.create_table(
        "flight_seats",
        sa.Column("flight_id", sa.String(length=64), nullable=False),
        sa.Column("seat_number", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("held_for_reservation_id", sa.String(length=64), nullable=True),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('AVAILABLE', 'HELD', 'BOOKED', 'UNAVAILABLE')",
            name="ck_flight_seats_status",
        ),
        sa.CheckConstraint(
            "status <> 'HELD' OR hold_expires_at IS NOT NULL",
            name="ck_flight_seats_held_has_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["flight_id"],
            ["inventory.flights.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("flight_id", "seat_number"),
        schema="inventory",
    )


def downgrade() -> None:
    op.drop_table("flight_seats", schema="inventory")
    op.drop_index(
        "ix_inventory_flights_airline_id",
        table_name="flights",
        schema="inventory",
    )
    op.drop_index(
        "ix_flights_route_departure",
        table_name="flights",
        schema="inventory",
    )
    op.drop_table("flights", schema="inventory")
    op.drop_index(
        "ix_inventory_airports_city_id",
        table_name="airports",
        schema="inventory",
    )
    op.drop_table("airports", schema="inventory")
    op.drop_table("currencies", schema="inventory")
    op.drop_table("airlines", schema="inventory")
    op.drop_table("cities", schema="inventory")
    op.execute("DROP SCHEMA IF EXISTS inventory")
