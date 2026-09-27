from app.ingestion import OVERLAP_WORDS, TARGET_WORDS, chunk_pages


def test_chunks_track_pages_and_overlap():
    pages = [" ".join(f"p1w{i}" for i in range(300)), " ".join(f"p2w{i}" for i in range(300))]
    chunks = chunk_pages(pages)
    assert len(chunks) == 2
    first_from, first_to, first_text = chunks[0]
    assert (first_from, first_to) == (1, 2)
    assert len(first_text.split()) == TARGET_WORDS
    second_words = chunks[1][2].split()
    assert second_words[:OVERLAP_WORDS] == first_text.split()[-OVERLAP_WORDS:]


def test_empty_document_has_no_chunks():
    assert chunk_pages(["", "  "]) == []
