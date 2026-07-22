from collections.abc import Callable, Coroutine
from functools import wraps
from logging import getLogger
from typing import Any, ParamSpec, TypeVar

from openai import OpenAIError

from src.app.exceptions.embeddings import EmbeddingGenerationError

logger = getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


_AsyncFunc = Callable[P, Coroutine[Any, Any, R]]


def wrap_provider_errors(operation: str) -> Callable[[_AsyncFunc[P, R]], _AsyncFunc[P, R]]:
    """Translate provider SDK failures into the app's exception hierarchy.

    DRY: every provider call site needs the same "log it, then re-raise as our
    typed error" behaviour, so it is written once here instead of being copied
    into each method. Retry and backoff are deliberately *not* implemented here
    — the OpenAI SDK already does that, configured via EMBEDDING_MAX_RETRIES.
    """

    def decorator(func: _AsyncFunc[P, R]) -> _AsyncFunc[P, R]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)
            except OpenAIError as exc:
                logger.error("Embedding provider failed during %s: %s", operation, exc)
                raise EmbeddingGenerationError(
                    f"Embedding provider request failed during {operation}."
                ) from exc

        return wrapper

    return decorator
