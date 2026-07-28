import enum


class CustomerStatus(enum.StrEnum):
    """Lifecycle stage of a customer.

    Domain vocabulary lives in contracts/ rather than models/ so that the ORM
    column, the HTTP schema and the services all reference one definition
    instead of three copies that can drift apart.
    """

    ACTIVE = "active"
    LEAD = "lead"
    CHURNED = "churned"


class ResourceType(enum.StrEnum):
    """Kind of bookable resource.

    The operator behind this API runs a restaurant, a wellness clinic and a set
    of hireable meeting rooms, so `resource_type` is the parameter the agent
    services differ by: the voice agent books tables, the sales agent sells
    treatments. A clinic reserving a "table" was the tell that the demo data and
    the schema had drifted apart.
    """

    TABLE = "table"
    MEETING_ROOM = "meeting_room"
    TREATMENT_ROOM = "treatment_room"


class BookingStatus(enum.StrEnum):
    """Lifecycle of a reservation.

    A cancelled booking is kept rather than deleted: the cancellation is itself
    a fact the business needs — the published policy charges half price for
    cancelling inside 24 hours and tracks no-shows separately.
    """

    ACTIVE = "active"
    CANCELLED = "cancelled"
