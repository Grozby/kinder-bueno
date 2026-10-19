from navigator.ingest.chunk import CHUNK_OVERLAP, CHUNK_SIZE, chunk_page, pack_blocks, split_blocks


def _text(n_lines: int, line_len: int = 90) -> str:
    return "\n".join(f"line{i:03d} " + "x" * (line_len - 8) for i in range(n_lines))


def test_empty_text_gives_no_chunks():
    assert chunk_page("Title", "") == []
    assert chunk_page("Title", " \n\n \n") == []


def test_short_page_is_one_chunk_with_title_prefix():
    assert chunk_page("Diabetes Center", "Glucose sensors.\n\nInsulin pumps.") == [
        "Diabetes Center\n\nGlucose sensors.\nInsulin pumps."
    ]


def test_missing_title_gives_no_prefix():
    assert chunk_page(None, "Some text.") == ["Some text."]
    assert chunk_page("  ", "Some text.") == ["Some text."]


def test_chunk_sizes_stay_near_the_target():
    bodies = pack_blocks(split_blocks(_text(100)))
    assert len(bodies) > 5
    assert all(len(b) <= CHUNK_SIZE + CHUNK_OVERLAP for b in bodies)
    assert all(len(b) >= CHUNK_SIZE - 100 for b in bodies[:-1])


def test_consecutive_chunks_overlap():
    bodies = pack_blocks(split_blocks(_text(100)))
    for prev, nxt in zip(bodies, bodies[1:]):
        head = nxt.split("\n")[0]
        assert prev.endswith(head)
        assert 0 < len(head) <= CHUNK_OVERLAP


def test_every_line_is_kept():
    text = _text(60)
    joined = "\n".join(pack_blocks(split_blocks(text)))
    for line in text.split("\n"):
        assert line in joined


def test_long_block_is_split_at_word_boundaries():
    words = " ".join(f"word{i}" for i in range(1000))
    blocks = split_blocks(words, max_len=CHUNK_SIZE)
    assert len(blocks) > 1
    assert all(len(b) <= CHUNK_SIZE for b in blocks)
    assert " ".join(blocks) == words


def test_every_chunk_has_the_title():
    chunks = chunk_page("ARTORG", _text(50))
    assert len(chunks) > 1
    assert all(c.startswith("ARTORG\n\n") for c in chunks)
