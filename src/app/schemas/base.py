from pydantic import BaseModel, ConfigDict


class ResponseModel(BaseModel):
    """Base of every response schema: built straight from a contract dataclass."""

    model_config = ConfigDict(from_attributes=True)
