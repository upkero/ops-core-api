from src.app.exceptions.base import BaseAppException


class EntityNotFoundError(BaseAppException):
    """Raised when a requested aggregate does not exist."""

    status_code = 404
    error_code = "entity_not_found"
    default_detail = "Requested entity was not found."


class SlotUnavailableError(BaseAppException):
    """Raised when a booking slot is already taken."""

    status_code = 409
    error_code = "slot_unavailable"
    default_detail = "Booking slot is no longer available."


class SlotCapacityExceededError(BaseAppException):
    """Raised when the requested party does not fit the slot."""

    status_code = 409
    error_code = "slot_capacity_exceeded"
    default_detail = "Party size exceeds the capacity of this slot."
