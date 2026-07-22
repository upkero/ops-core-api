import re

DEFAULT_MAX_CHARS = 400
DEFAULT_OVERLAP = 80

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """Split a document into retrieval-sized chunks.

    Prefers natural boundaries — paragraphs first, then sentences — so a chunk
    is a coherent passage rather than an arbitrary window. Overlap is applied
    only where text has to be cut mid-sentence, because that is the only case
    where a boundary can strand the answer across two chunks.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars.")

    units: list[str] = []
    for paragraph in (part.strip() for part in _PARAGRAPH_BREAK.split(text)):
        if not paragraph:
            continue
        if len(paragraph) <= max_chars:
            units.append(paragraph)
        else:
            units.extend(_split_paragraph(paragraph, max_chars, overlap))

    chunks = _pack(units, max_chars, separator="\n\n")
    return chunks or ([stripped] if (stripped := text.strip()) else [])


def _split_paragraph(paragraph: str, max_chars: int, overlap: int) -> list[str]:
    sentences: list[str] = []
    for sentence in _SENTENCE_BREAK.split(paragraph):
        if len(sentence) > max_chars:
            sentences.extend(_hard_split(sentence, max_chars, overlap))
        elif sentence:
            sentences.append(sentence)
    return _pack(sentences, max_chars, separator=" ")


def _hard_split(text: str, max_chars: int, overlap: int) -> list[str]:
    step = max_chars - overlap
    return [text[start : start + max_chars] for start in range(0, len(text), step)]


def _pack(units: list[str], max_chars: int, *, separator: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(separator) + len(unit) > max_chars:
            chunks.append(current)
            current = unit
        else:
            current = f"{current}{separator}{unit}" if current else unit
    if current:
        chunks.append(current)
    return chunks
