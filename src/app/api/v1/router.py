from fastapi import APIRouter, Depends

from src.app.api.v1.dependencies.security import require_api_key
from src.app.api.v1.routers.booking_slots import router as booking_slots_router
from src.app.api.v1.routers.bookings import router as bookings_router
from src.app.api.v1.routers.customers import router as customers_router
from src.app.api.v1.routers.documents import router as documents_router
from src.app.api.v1.routers.pricing import router as pricing_router

# Every endpoint under /api/v1 needs the key — declared once here rather than
# repeated per route, so a new router cannot be added unprotected by accident.
# /health stays open: it is mounted separately and the container runtime polls it.
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])

api_router.include_router(customers_router)
api_router.include_router(booking_slots_router)
api_router.include_router(bookings_router)
api_router.include_router(pricing_router)
api_router.include_router(documents_router)
