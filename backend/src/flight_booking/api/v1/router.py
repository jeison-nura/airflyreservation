from fastapi import APIRouter

from flight_booking.modules.inventory.adapters.http.router import (
    router as inventory_router,
)
from flight_booking.modules.payments.adapters.http.router import (
    router as payments_router,
)
from flight_booking.modules.reservations.adapters.http.router import (
    router as reservations_router,
)

router = APIRouter()
router.include_router(inventory_router, prefix="/inventory", tags=["inventory"])
router.include_router(reservations_router, prefix="/reservations", tags=["reservations"])
router.include_router(payments_router, prefix="/payments", tags=["payments"])
