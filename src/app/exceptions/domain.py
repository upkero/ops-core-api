from src.app.exceptions.base import BaseAppException


class InvalidInputError(BaseAppException, ValueError):
    """Raised when arguments reaching a service are unusable.

    A plain ValueError here would escape the handler hierarchy and surface as a
    500, telling the caller the server broke when in fact their input was wrong.
    """

    status_code = 422
    error_code = "invalid_input"
    default_detail = "Invalid input."


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


class IdempotencyKeyReusedError(BaseAppException):
    """Raised when a retry token is replayed with different parameters.

    Returning the stored booking would answer a question the caller did not
    ask; failing loudly surfaces the bug in whoever generates the keys.
    """

    status_code = 409
    error_code = "idempotency_key_reused"
    default_detail = "This Idempotency-Key was already used for a different booking."


class SlotCapacityExceededError(BaseAppException):
    """Raised when the requested party does not fit the slot."""

    status_code = 409
    error_code = "slot_capacity_exceeded"
    default_detail = "Party size exceeds the capacity of this slot."
