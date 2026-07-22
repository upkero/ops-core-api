import pytest

from src.app.services.knowledge import chunk_text


def test_short_text_is_a_single_chunk() -> None:
    assert chunk_text("One short sentence.") == ["One short sentence."]


def test_empty_text_produces_no_chunks() -> None:
    assert chunk_text("   \n\n  ") == []


def test_paragraphs_are_packed_up_to_the_limit() -> None:
    text = "\n\n".join(["A" * 150, "B" * 150, "C" * 150])

    chunks = chunk_text(text, max_chars=400, overlap=0)

    # 150 + 2 + 150 = 302 fits; adding the third would exceed 400.
    assert len(chunks) == 2
    assert all(len(chunk) <= 400 for chunk in chunks)


def test_a_long_paragraph_is_split_on_sentence_boundaries() -> None:
    text = " ".join(f"Sentence number {i} padded out with filler words." for i in range(20))

    chunks = chunk_text(text, max_chars=200, overlap=0)

    assert len(chunks) > 1
    assert all(len(chunk) <= 200 for chunk in chunks)
    # Splitting on sentence ends means no chunk starts mid-sentence.
    assert all(chunk.startswith("Sentence") for chunk in chunks)


def test_a_sentence_longer_than_the_limit_is_hard_split_with_overlap() -> None:
    text = "word " * 200  # 1000 chars, no sentence boundary at all

    chunks = chunk_text(text, max_chars=100, overlap=20)

    assert all(len(chunk) <= 100 for chunk in chunks)
    # Overlap only matters here, where the cut lands mid-sentence: the tail of
    # one chunk must reappear at the head of the next.
    assert chunks[0][-20:] == chunks[1][:20]


def test_every_chunk_is_within_the_limit_for_realistic_prose() -> None:
    text = "\n\n".join(
        [
            "Appointments can be cancelled up to twenty-four hours before the start time. " * 4,
            "Cancellations inside that window are charged at fifty percent. " * 4,
        ]
    )

    assert all(len(chunk) <= 400 for chunk in chunk_text(text))


@pytest.mark.parametrize(("max_chars", "overlap"), [(0, 0), (100, 100), (100, 150), (100, -1)])
def test_invalid_configuration_is_rejected(max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text("some text", max_chars=max_chars, overlap=overlap)
