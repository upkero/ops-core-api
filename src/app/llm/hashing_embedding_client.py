import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

from src.app.exceptions.embeddings import EmbeddingInputError
from src.app.interfaces.llm.embedding_client import EmbeddingClient

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Character n-grams are prefixed so they can never collide with a real word,
# and weighted below whole words so that an exact term still wins.
_NGRAM_SIZE = 4
_NGRAM_PREFIX = "#"
_NGRAM_WEIGHT = 0.5

# Trimming the highest-frequency function words keeps a query like
# "how do I cancel my appointment" from being dominated by "how/do/i/my".
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "do", "does",
        "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is",
        "it", "its", "me", "my", "no", "not", "of", "on", "or", "our", "so", "that",
        "the", "their", "them", "then", "there", "these", "they", "this", "to",
        "was", "we", "were", "what", "when", "where", "which", "who", "will",
        "with", "would", "you", "your",
    }
)  # fmt: skip


class HashingEmbeddingClient(EmbeddingClient):
    """Deterministic local embeddings via the hashing trick.

    Not a semantic model: it captures lexical overlap, which is enough for the
    demo to return sensible results and for tests to be reproducible, and it
    means `docker compose up` works with no API key and no network. Swap in the
    OpenAI-compatible client (EMBEDDING_PROVIDER=openai) for real semantics.
    """

    def __init__(self, *, dimensions: int) -> None:
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return "hashing"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_query(self, text: str) -> Sequence[float]:
        if not text.strip():
            raise EmbeddingInputError("Cannot embed empty text.")
        return self._embed(text)

    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            raise EmbeddingInputError("Cannot embed an empty batch.")
        return [await self.embed_query(text) for text in texts]

    async def close(self) -> None:
        return None

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for feature, count in Counter(self._features(text)).items():
            weight = _NGRAM_WEIGHT if feature.startswith(_NGRAM_PREFIX) else 1.0
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            # Signed buckets: without the sign, unrelated texts drift towards a
            # common positive direction and every pair looks similar.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * weight * (1.0 + math.log(count))

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Text with no usable tokens ("!!!") would otherwise be a zero
            # vector, and cosine distance against zero is NaN — which would
            # silently corrupt the ranking rather than fail.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    @classmethod
    def _features(cls, text: str) -> list[str]:
        """Whole words plus character n-grams.

        Word-only matching misses morphology: a query for "cancel" would score
        zero against a chunk saying "cancelled", because the two share no
        token. Their n-grams do overlap, so the n-grams carry the recall while
        the whole word — weighted higher — carries the precision.
        """
        features: list[str] = []
        for token in cls._tokens(text):
            features.append(token)
            if len(token) > _NGRAM_SIZE:
                features.extend(
                    f"{_NGRAM_PREFIX}{token[i : i + _NGRAM_SIZE]}" for i in range(len(token) - _NGRAM_SIZE + 1)
                )
        return features

    @staticmethod
    def _tokens(text: str) -> list[str]:
        tokens = [token for token in _TOKEN_PATTERN.findall(text.lower()) if token not in _STOPWORDS]
        # Fall back to the unfiltered tokens rather than embedding nothing when
        # a short query is made entirely of stopwords ("how do I").
        return tokens or _TOKEN_PATTERN.findall(text.lower())
