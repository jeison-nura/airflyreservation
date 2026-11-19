"""One-time metadata update for databases that already applied the old Inventory ID.

Does not change tables or data. Run before using Alembic with the renamed revision.
"""

import asyncio

from sqlalchemy import text

from flight_booking.modules.inventory.adapters.persistence.session import engine

OLD_REVISION = "0001_inventory_flights"
NEW_REVISION = "01a1f1807fbb7f1b93c235d8438ae314"


async def main() -> None:
    async with engine.begin() as connection:
        versions = (
            await connection.execute(text("SELECT version_num FROM alembic_version FOR UPDATE"))
        ).scalars().all()
        if versions == [NEW_REVISION]:
            print("Inventory revision already updated")
            return
        if versions != [OLD_REVISION]:
            raise RuntimeError(f"Expected only the legacy Inventory revision; found {versions}")
        if (
            await connection.scalar(text("SELECT to_regclass('inventory.flight_seats')"))
            is None
        ):
            raise RuntimeError("Inventory schema is missing; refusing to change revision")
        await connection.execute(
            text("UPDATE alembic_version SET version_num = :new WHERE version_num = :old"),
            {"new": NEW_REVISION, "old": OLD_REVISION},
        )
    print("Inventory revision metadata updated; no tables or data changed")


if __name__ == "__main__":
    asyncio.run(main())
