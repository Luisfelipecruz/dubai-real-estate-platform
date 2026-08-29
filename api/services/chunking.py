"""Chunking. One strategy per source, because one strategy for all three is wrong for all three.

The corpus has three sources and they are not the same shape:

  docs/*.md    long, hierarchical, full of code blocks. Structure-aware split.
  area sheets  ~120 tokens, internally coherent. Never split.
  area_notes   short, authored as units. Split only when genuinely oversized.

Two rules do most of the work here.

**Heading paths are prepended to the embedded text.** A chunk pulled out of the middle
of a document has lost the thing that made it interpretable: its position. `changelog.md
> v0.5.0 > The synthetic rent key` costs nine tokens and gives that back. Without it, a
chunk reading "the key is (contract_id, line_number)" is about nothing in particular.

**Code blocks are never split.** A truncated SQL statement is worse than no SQL
statement, because it retrieves and then misleads -- it looks like an answer. A fenced
block longer than the target becomes its own chunk instead, heading path attached.

Everything in this module is a pure function over strings. No database, no network, no
model. That is what makes the chunk-boundary tests in api/tests/test_chunking.py fast
and deterministic, and it is why they can assert on behaviour that is otherwise only
observable as a vague drop in retrieval quality.
"""

import hashlib
import re
from dataclasses import dataclass

# Target and overlap in ESTIMATED tokens -- see estimate_tokens for what that means.
DEFAULT_TARGET_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64

# Headings at or above this level force a chunk boundary. h4 and deeper are treated as
# body text: splitting on them produces chunks too small to carry an argument.
SPLIT_LEVEL = 3

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# Named groups, not a bare alternation. `str.isalnum()` is False for
# `meter_sale_price` because of the underscore, so branching on it counted a
# 16-character identifier as a single token -- the exact underestimate that ends in
# silent truncation. The group tells word from punctuation without guessing.
_PIECE_RE = re.compile(r"(?P<word>\w+)|(?P<punct>[^\w\s])")

# Sentence boundary for splitting oversized prose. Deliberately crude: it only has to
# be better than cutting mid-word, and a full sentence tokenizer is a dependency.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit. `content` is the body; `heading_path` is stored separately
    so it can be displayed as a breadcrumb, but both go into the embedded text."""

    source_type: str  # doc | area_sheet | note
    source_id: str
    chunk_index: int
    heading_path: str
    content: str
    est_tokens: int

    @property
    def embed_text(self) -> str:
        """Exactly what gets embedded and hashed. Heading path first, so the model sees
        the context before the claim."""
        if self.heading_path:
            return f"{self.heading_path}\n\n{self.content}"
        return self.content

    @property
    def content_hash(self) -> str:
        """sha256 over the embedded text, not the body alone.

        Deliberate: restructuring a document changes its heading paths without changing
        a word of body text. Hashing the body only would leave those chunks looking
        unchanged, and the index would keep serving vectors built from a hierarchy that
        no longer exists.
        """
        return hashlib.sha256(self.embed_text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Approximate the BGE (WordPiece) token count without loading a tokenizer.

    This is an ESTIMATE and the name says so. The real count comes back from the
    embeddings service, which has the actual tokenizer, and that is what gets stored in
    `doc_chunks.token_count`. This function exists only to pick boundaries, where being
    exactly right matters far less than being cheap and consistent.

    WordPiece splits on punctuation and breaks unknown or long words into pieces of
    roughly four characters. Modelling it that way makes the estimate deliberately
    conservative on code and identifiers -- `meter_sale_price` counts as five rather
    than one -- which is the direction to err in: the failure mode of underestimating
    is silent truncation at the model's 512-token limit.
    """
    total = 0
    for match in _PIECE_RE.finditer(text):
        if match.lastgroup == "word":
            total += max(1, -(-len(match.group()) // 4))
        else:
            total += 1
    return total


def _tail_words(text: str, budget_tokens: int) -> str:
    """Last `budget_tokens` worth of text, cut on a word boundary. Used for overlap."""
    words = text.split()
    kept: list[str] = []
    used = 0
    for word in reversed(words):
        cost = estimate_tokens(word)
        if used + cost > budget_tokens:
            break
        kept.append(word)
        used += cost
    return " ".join(reversed(kept))


def _split_prose(text: str, target_tokens: int) -> list[str]:
    """Split one oversized prose block on sentence boundaries, then on words.

    Code blocks are atomic on purpose; prose is not, and the two must not share a
    policy. A 16,000-token note emitted as one chunk does not fail -- it is embedded,
    stored, and silently truncated at the model's 512-token sequence limit, leaving
    everything after the first paragraph unfindable by the dense arm forever.
    """
    units: list[str] = []
    for sentence in _SENTENCE_RE.split(text):
        if estimate_tokens(sentence) <= target_tokens:
            units.append(sentence)
            continue
        # A single sentence over the target -- a wall of text with no punctuation.
        # Fall back to word boundaries; never cut inside a word.
        words = sentence.split()
        current: list[str] = []
        used = 0
        for word in words:
            cost = estimate_tokens(word)
            if current and used + cost > target_tokens:
                units.append(" ".join(current))
                current, used = [], 0
            current.append(word)
            used += cost
        if current:
            units.append(" ".join(current))

    packed: list[str] = []
    current_unit: list[str] = []
    used = 0
    for unit in units:
        cost = estimate_tokens(unit)
        if current_unit and used + cost > target_tokens:
            packed.append(" ".join(current_unit))
            current_unit, used = [], 0
        current_unit.append(unit)
        used += cost
    if current_unit:
        packed.append(" ".join(current_unit))
    return packed


@dataclass
class _Block:
    kind: str  # heading | text | code
    level: int  # heading level, else 0
    text: str


def _parse_blocks(markdown: str) -> list[_Block]:
    """Split markdown into headings, paragraphs and atomic fenced code blocks.

    Fence tracking is not optional. `# Extensions` inside a ```sql block is a SQL
    comment, and treating it as an h1 would both corrupt the heading path and split the
    block in half -- the two failures this module exists to prevent, in one line.
    """
    blocks: list[_Block] = []
    buffer: list[str] = []
    fence: str | None = None

    def flush_text() -> None:
        joined = "\n".join(buffer).strip("\n")
        if joined.strip():
            blocks.append(_Block("text", 0, joined))
        buffer.clear()

    for line in markdown.splitlines():
        fence_match = _FENCE_RE.match(line)

        if fence is not None:
            buffer.append(line)
            if fence_match and fence_match.group(1) == fence:
                blocks.append(_Block("code", 0, "\n".join(buffer)))
                buffer.clear()
                fence = None
            continue

        if fence_match:
            flush_text()
            fence = fence_match.group(1)
            buffer.append(line)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_text()
            blocks.append(_Block("heading", len(heading.group(1)), heading.group(2)))
            continue

        if not line.strip():
            flush_text()
            continue

        buffer.append(line)

    # An unterminated fence is a malformed document, not a reason to lose its tail.
    if fence is not None:
        blocks.append(_Block("code", 0, "\n".join(buffer)))
    else:
        flush_text()

    return blocks


def _heading_path(root: str, stack: dict[int, str]) -> str:
    parts = [root]
    for level in sorted(stack):
        title = stack[level]
        # Drop a level-1 heading that just restates the filename: 'changelog.md >
        # Changelog > v0.5.0' carries no more information than 'changelog.md > v0.5.0'.
        if level == 1 and title.strip().lower() == root.rsplit(".", 1)[0].lower():
            continue
        parts.append(title)
    return " > ".join(parts)


def chunk_markdown(
    markdown: str,
    source_id: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Structure-aware split of a markdown document.

    Boundaries come from headings first and size second. Splitting on character count
    instead would throw away the semantic boundaries the author already wrote down --
    which is the single most common way a RAG corpus is degraded before retrieval is
    ever attempted.

    Overlap is applied only between continuation chunks of the SAME section, never
    across a heading. Across a heading, the heading path already carries the context
    that overlap exists to restore, and duplicating a section's opening lines into the
    previous section makes both of them retrievable for the wrong query.
    """
    root = source_id.rsplit("/", 1)[-1]
    stack: dict[int, str] = {}
    chunks: list[Chunk] = []

    pending: list[str] = []
    pending_tokens = 0
    path_at_start = root
    is_continuation = False

    def flush() -> None:
        nonlocal pending, pending_tokens, is_continuation
        body = "\n\n".join(pending).strip()
        if not body:
            pending, pending_tokens = [], 0
            return
        chunks.append(
            Chunk(
                source_type="doc",
                source_id=source_id,
                chunk_index=len(chunks),
                heading_path=path_at_start,
                content=body,
                est_tokens=estimate_tokens(body),
            )
        )
        carry = _tail_words(body, overlap_tokens) if overlap_tokens > 0 else ""
        pending = [carry] if carry else []
        pending_tokens = estimate_tokens(carry) if carry else 0
        is_continuation = True

    # Expand oversized prose blocks before packing, so the overlap and heading-path
    # logic below sees only blocks that can actually fit in a chunk.
    blocks: list[_Block] = []
    for parsed in _parse_blocks(markdown):
        if parsed.kind == "text" and estimate_tokens(parsed.text) > target_tokens:
            blocks.extend(
                _Block("text", 0, piece)
                for piece in _split_prose(parsed.text, target_tokens)
            )
        else:
            blocks.append(parsed)

    for block in blocks:
        if block.kind == "heading":
            if block.level <= SPLIT_LEVEL:
                flush()
                # A new section starts clean: drop the overlap carried from the last
                # one, since it belongs to a different heading path.
                pending, pending_tokens, is_continuation = [], 0, False
            for deeper in [lv for lv in stack if lv >= block.level]:
                del stack[deeper]
            stack[block.level] = block.text
            path_at_start = _heading_path(root, stack)
            if block.level > SPLIT_LEVEL:
                # h4+ stays inline as a body line so its text remains retrievable.
                pending.append(f"{'#' * block.level} {block.text}")
                pending_tokens += estimate_tokens(block.text)
            continue

        block_tokens = estimate_tokens(block.text)

        if block.kind == "code" and block_tokens > target_tokens:
            # Oversized fenced block: emit it whole, on its own, rather than cutting a
            # statement in half. Its heading path is what makes it interpretable.
            flush()
            pending, pending_tokens = [], 0
            chunks.append(
                Chunk(
                    source_type="doc",
                    source_id=source_id,
                    chunk_index=len(chunks),
                    heading_path=path_at_start,
                    content=block.text,
                    est_tokens=block_tokens,
                )
            )
            is_continuation = True
            continue

        if pending and pending_tokens + block_tokens > target_tokens:
            flush()
            path_at_start = _heading_path(root, stack)

        pending.append(block.text)
        pending_tokens += block_tokens

    if pending and "".join(pending).strip():
        # Guard against emitting a chunk that is nothing but the overlap tail of the
        # previous one -- that is a duplicate, and duplicates distort recall upward.
        body = "\n\n".join(pending).strip()
        if not (is_continuation and chunks and body in chunks[-1].content):
            chunks.append(
                Chunk(
                    source_type="doc",
                    source_id=source_id,
                    chunk_index=len(chunks),
                    heading_path=path_at_start,
                    content=body,
                    est_tokens=estimate_tokens(body),
                )
            )

    return chunks


def chunk_area_sheet(text: str, area_name: str) -> list[Chunk]:
    """One chunk per area. Never split.

    A fact sheet is ~120 tokens and every sentence in it is about the same place.
    Splitting would separate the area's name from its numbers, which is the worst
    possible cut: the half carrying the numbers becomes unfindable, and the half
    carrying the name answers with no numbers.
    """
    return [
        Chunk(
            source_type="area_sheet",
            source_id=area_name,
            chunk_index=0,
            heading_path=f"Area fact sheet > {area_name}",
            content=text.strip(),
            est_tokens=estimate_tokens(text),
        )
    ]


def chunk_note(
    text: str,
    note_id: int | str,
    area_name: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """One chunk per note, split only if genuinely oversized.

    Notes are written as units by a human. The default is to keep them whole; the split
    path exists so that a pathologically long note cannot be silently truncated at the
    model's sequence limit.
    """
    body = text.strip()
    source_id = f"note:{note_id}"
    path = f"Analyst note > {area_name}"

    if estimate_tokens(body) <= target_tokens:
        return [
            Chunk(
                source_type="note",
                source_id=source_id,
                chunk_index=0,
                heading_path=path,
                content=body,
                est_tokens=estimate_tokens(body),
            )
        ]

    parts = chunk_markdown(
        body,
        source_id,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
    )
    return [
        Chunk(
            source_type="note",
            source_id=source_id,
            chunk_index=i,
            heading_path=path,
            content=part.content,
            est_tokens=part.est_tokens,
        )
        for i, part in enumerate(parts)
    ]
