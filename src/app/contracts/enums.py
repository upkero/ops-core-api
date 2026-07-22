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
    """Kind of bookable resource."""

    TABLE = "table"
    MEETING_ROOM = "meeting_room"
