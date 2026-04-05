"""Adaptive document chunking by doc_type.

Chunk sizes (in tokens, approx 4 chars/token):
  api_reference / cli_reference: 400-500 tokens, 50 token overlap
  admin_guide / tutorial:        800 tokens, 50 token overlap
  config_example:                600 tokens, 0 overlap (natural boundaries)
"""
import re

# Token targets (chars = tokens * 4)
_TARGETS = {
    "api_reference":  (1600, 2000, 200),   # (min_chars, max_chars, overlap_chars)
    "cli_reference":  (1600, 2000, 200),
    "admin_guide":    (2400, 3200, 200),
    "tutorial":       (2400, 3200, 200),
    "config_example": (1600, 2400, 0),
}

_DEFAULT_TARGET = (2400, 3200, 200)

# Config block start patterns — used for config_example splitting
_CONFIG_BLOCK_RE = re.compile(
    r"^(?:"
    r"server\s*\{|"                    # nginx server {}
    r"location\s+\S+\s*\{|"           # nginx location {}
    r"upstream\s+\S+\s*\{|"           # nginx upstream {}
    r"-\s+name:\s|"                    # ansible task
    r"-\s+hosts:\s|"                   # ansible play
    r'resource\s+"[^"]+"\s+"[^"]+"|'   # terraform resource
    r'data\s+"[^"]+"\s+"[^"]+"|'       # terraform data
    r"module\s+\"|"                    # terraform module
    r"config\s+\w|"                    # FortiGate config
    r"edit\s+\d|"                      # FortiGate edit
    r"end$|"                           # FortiGate end
    r"\[[\w.]+\]"                      # INI section
    r")",
    re.MULTILINE,
)

# Heading patterns for structured docs
_HEADING_RE = re.compile(r"^#{1,4}\s+.+$|^[A-Z][A-Za-z ]{3,60}$", re.MULTILINE)


def chunk_document(text: str, doc_type: str) -> list[str]:
    """Split text into chunks using strategy appropriate for doc_type.

    Returns list of non-empty chunk strings.
    """
    if not text or not text.strip():
        return []

    if doc_type == "config_example":
        return _chunk_config(text)

    _, max_chars, overlap = _TARGETS.get(doc_type, _DEFAULT_TARGET)
    return _chunk_prose(text, max_chars, overlap)


def _chunk_prose(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split prose/docs on heading or paragraph boundaries with overlap."""
    # Try to split on headings first
    sections = _HEADING_RE.split(text)

    # If no headings found, split on double-newlines (paragraphs)
    if len(sections) <= 1:
        sections = re.split(r"\n\n+", text)

    chunks = []
    current = ""

    for section in sections:
        section = section.strip()
        if not section:
            continue

        if len(current) + len(section) + 1 <= max_chars:
            current = f"{current}\n\n{section}" if current else section
        else:
            if current:
                chunks.append(current.strip())
            # If a single section exceeds max, split it further on sentences
            if len(section) > max_chars:
                sub_chunks = _split_on_sentences(section, max_chars)
                chunks.extend(sub_chunks[:-1])
                current = sub_chunks[-1] if sub_chunks else ""
            else:
                current = section

    if current.strip():
        chunks.append(current.strip())

    # Apply overlap
    if overlap > 0 and len(chunks) > 1:
        chunks = _apply_overlap(chunks, overlap)

    return [c for c in chunks if c.strip()]


def _chunk_config(text: str) -> list[str]:
    """Split config files on logical block boundaries. Zero overlap."""
    # Find all block start positions
    matches = list(_CONFIG_BLOCK_RE.finditer(text))

    if not matches:
        # No recognized blocks — fall back to paragraph splitting
        return _chunk_prose(text, 2400, 0)

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            # Split oversized blocks
            if len(block) > 2400:
                chunks.extend(_split_on_sentences(block, 2400))
            else:
                chunks.append(block)

    # Include any content before the first block
    if matches and matches[0].start() > 0:
        preamble = text[:matches[0].start()].strip()
        if preamble:
            chunks.insert(0, preamble)

    return [c for c in chunks if c.strip()]


def _split_on_sentences(text: str, max_chars: int) -> list[str]:
    """Last-resort split on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 <= max_chars:
            current = f"{current} {s}" if current else s
        else:
            if current:
                chunks.append(current.strip())
            current = s
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _apply_overlap(chunks: list[str], overlap_chars: int) -> list[str]:
    """Prepend the last overlap_chars of the previous chunk to the next."""
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-overlap_chars:]
        # Find a word boundary to avoid splitting mid-word
        space_idx = prev_tail.find(" ")
        if space_idx > 0:
            prev_tail = prev_tail[space_idx + 1:]
        result.append(f"{prev_tail}\n{chunks[i]}")
    return result
