from fastapi import APIRouter

from src.app.api.v1.routers.booking_slots import router as booking_slots_router
from src.app.api.v1.routers.bookings import router as bookings_router
from src.app.api.v1.routers.customers import router as customers_router
from src.app.api.v1.routers.pricing import router as pricing_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(customers_router)
api_router.include_router(booking_slots_router)
api_router.include_router(bookings_router)
api_router.include_router(pricing_router)
