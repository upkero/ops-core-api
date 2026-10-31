from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ResponseModel(BaseModel):
    """Base of every response schema: built straight from a contract dataclass."""

    model_config = ConfigDict(from_attributes=True)


# Stripped before the length check, so "   " is rejected as empty rather than accepted as a name.
NonBlankName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
