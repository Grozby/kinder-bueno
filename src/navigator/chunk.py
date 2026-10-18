"""Split cleaned page text into overlapping, title-prefixed chunks."""

import re

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def split_blocks(text: str, max_len: int = CHUNK_SIZE) -> list[str]:
    """Split on line breaks (the cleaner puts one block per line); hard-split blocks longer than `max_len`."""
    blocks = []
    for line in re.split(r"\n+", text):
        line = line.strip()
        while len(line) > max_len:
            cut = line.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            blocks.append(line[:cut])
            line = line[cut:].strip()
        if line:
            blocks.append(line)
    return blocks


def _tail(text: str, overlap: int) -> str:
    """The last ~`overlap` characters of `text`, starting at a word boundary."""
    if len(text) <= overlap:
        return text
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def pack_blocks(blocks: list[str], size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Pack blocks into chunks of about `size` characters; each chunk starts with the tail of the previous one."""
    chunks: list[str] = []
    current = ""
    has_new = False  # does `current` hold anything beyond the overlap tail?
    for block in blocks:
        if has_new and len(current) + 1 + len(block) > size:
            chunks.append(current)
            current, has_new = _tail(current, overlap), False
        current = f"{current}\n{block}" if current else block
        has_new = True
    if has_new:
        chunks.append(current)
    return chunks


def chunk_page(title: str | None, text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Chunks of a page, each prefixed with the page title: "<title>\\n\\n<chunk text>"."""
    bodies = pack_blocks(split_blocks(text, size), size, overlap)
    title = (title or "").strip()
    return [f"{title}\n\n{body}" if title else body for body in bodies]
