"""Chunking tests.

Everything here is pure -- no database, no model, no network -- which is the point.
Bad chunk boundaries do not raise. They show up as a vague, unattributable drop in
answer quality weeks later, by which time the retriever, the prompt and the model are
all suspects. These assertions turn that class of bug into a red test.
"""

from services.chunking import (
    DEFAULT_TARGET_TOKENS,
    chunk_area_sheet,
    chunk_markdown,
    chunk_note,
    estimate_tokens,
)


def test_heading_path_is_built_from_the_hierarchy():
    md = """# Changelog

## v0.5.0

### The synthetic rent key

The key is (contract_id, line_number).
"""
    chunks = chunk_markdown(md, "docs/changelog.md")
    leaf = [c for c in chunks if "synthetic" in c.heading_path]
    assert leaf, f"no chunk carried the h3 in its path: {[c.heading_path for c in chunks]}"
    assert leaf[0].heading_path == "changelog.md > v0.5.0 > The synthetic rent key"


def test_level_one_heading_matching_the_filename_is_not_repeated():
    """'changelog.md > Changelog > v0.5.0' carries no more information than
    'changelog.md > v0.5.0', and costs tokens in every chunk of the file."""
    md = "# Changelog\n\n## v0.5.0\n\nSomething happened.\n"
    chunks = chunk_markdown(md, "docs/changelog.md")
    assert all("Changelog >" not in c.heading_path for c in chunks)


def test_heading_path_is_part_of_the_embedded_text():
    """A chunk without its position is about nothing in particular."""
    md = "## Deduplication\n\nThe key is (contract_id, line_number).\n"
    chunk = chunk_markdown(md, "docs/data-model.md")[0]
    assert chunk.embed_text.startswith("data-model.md > Deduplication")
    assert "contract_id" in chunk.embed_text
    # ...but `content` stays clean, so the API can render the breadcrumb separately.
    assert not chunk.content.startswith("data-model.md")


def test_code_block_is_never_split():
    body = "\n".join(f"SELECT col_{i} FROM t WHERE x = {i};" for i in range(120))
    md = f"## Query\n\nBefore.\n\n```sql\n{body}\n```\n\nAfter.\n"
    chunks = chunk_markdown(md, "docs/x.md", target_tokens=100)

    fenced = [c for c in chunks if "```sql" in c.content]
    assert len(fenced) == 1, "the fence was split across chunks"
    assert fenced[0].content.count("```") == 2, "chunk holds an unterminated fence"
    assert "SELECT col_0" in fenced[0].content
    assert "SELECT col_119" in fenced[0].content


def test_oversized_code_block_becomes_its_own_chunk_with_its_heading_path():
    """A truncated SQL statement is worse than no SQL statement: it retrieves, and
    then it misleads. So an oversized block is emitted whole and alone."""
    body = "\n".join(f"SELECT col_{i};" for i in range(400))
    md = f"## Plans\n\n### EXPLAIN output\n\n```\n{body}\n```\n"
    chunks = chunk_markdown(md, "docs/plans.md", target_tokens=100)

    fenced = [c for c in chunks if "```" in c.content]
    assert len(fenced) == 1
    assert fenced[0].content.startswith("```")
    assert fenced[0].heading_path == "plans.md > Plans > EXPLAIN output"


def test_hash_inside_a_fence_is_not_treated_as_a_heading():
    """`# Extensions` inside a ```sql block is a SQL comment. Reading it as an h1 would
    corrupt the heading path AND split the block -- both failures in one line."""
    md = "## Setup\n\n```bash\n# Install\napt-get install postgresql-16-pgvector\n```\n"
    chunks = chunk_markdown(md, "docs/x.md")
    assert len(chunks) == 1
    assert chunks[0].heading_path == "x.md > Setup"
    assert "# Install" in chunks[0].content


def test_unterminated_fence_does_not_lose_the_tail():
    md = "## Broken\n\n```sql\nSELECT 1;\n"
    chunks = chunk_markdown(md, "docs/x.md")
    assert any("SELECT 1;" in c.content for c in chunks)


def test_oversized_section_splits_with_overlap():
    paragraphs = "\n\n".join(f"Paragraph {i} about rental yield in Dubai." for i in range(60))
    md = f"## Yield\n\n{paragraphs}\n"
    chunks = chunk_markdown(md, "docs/x.md", target_tokens=80, overlap_tokens=16)

    assert len(chunks) > 1, "an oversized section was not split"
    tail_words = set(chunks[0].content.split()[-6:])
    head_words = set(chunks[1].content.split()[:6])
    assert tail_words & head_words, "continuation chunks share no overlap"


def test_no_overlap_across_a_heading_boundary():
    """Across a heading the path already carries the context overlap exists to restore,
    and duplicating text makes both sections retrievable for the wrong query."""
    md = (
        "## Alpha\n\nAlpha talks about ZEBRAWOOD exclusively.\n\n"
        "## Beta\n\nBeta talks about QUINCE exclusively.\n"
    )
    chunks = chunk_markdown(md, "docs/x.md", target_tokens=1000, overlap_tokens=64)
    assert len(chunks) == 2
    assert "ZEBRAWOOD" not in chunks[1].content
    assert "QUINCE" not in chunks[0].content


def test_hash_is_stable_across_runs():
    md = "## A\n\nSome text about deduplication.\n"
    first = chunk_markdown(md, "docs/x.md")[0]
    second = chunk_markdown(md, "docs/x.md")[0]
    assert first.content_hash == second.content_hash


def test_hash_changes_when_only_the_heading_path_changes():
    """Restructuring a document changes what a chunk MEANS without changing a word of
    it. Hashing the body alone would leave those vectors stale and undetectable."""
    body = "The key is (contract_id, line_number)."
    a = chunk_markdown(f"## Deduplication\n\n{body}\n", "docs/x.md")[0]
    b = chunk_markdown(f"## Rent contracts\n\n{body}\n", "docs/x.md")[0]
    assert a.content == b.content
    assert a.content_hash != b.content_hash


def test_chunk_indexes_are_contiguous_from_zero():
    md = "\n".join(f"## Section {i}\n\nBody {i}.\n" for i in range(8))
    chunks = chunk_markdown(md, "docs/x.md")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_area_sheet_is_never_split():
    """Splitting a fact sheet is the worst possible cut: the half with the numbers
    becomes unfindable, and the half with the name answers with no numbers."""
    sheet = "**Dubai Marina.** " + ("18,432 recorded sales. " * 200)
    chunks = chunk_area_sheet(sheet, "Dubai Marina")
    assert len(chunks) == 1
    assert chunks[0].source_type == "area_sheet"
    assert chunks[0].heading_path == "Area fact sheet > Dubai Marina"
    assert chunks[0].est_tokens > DEFAULT_TARGET_TOKENS


def test_short_note_stays_whole():
    chunks = chunk_note("Yields here look overstated; check no_of_prop.", 7, "Al Qusais")
    assert len(chunks) == 1
    assert chunks[0].source_type == "note"
    assert chunks[0].source_id == "note:7"
    assert chunks[0].heading_path == "Analyst note > Al Qusais"


def test_pathologically_long_note_is_split_rather_than_truncated():
    body = " ".join(f"observation {i}" for i in range(4000))
    chunks = chunk_note(body, 8, "Dubai Marina")
    assert len(chunks) > 1
    assert all(c.heading_path == "Analyst note > Dubai Marina" for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_token_estimate_is_conservative_on_identifiers():
    """WordPiece splits `meter_sale_price` into several pieces. Underestimating is the
    dangerous direction -- it ends in silent truncation at the model's 512-token limit."""
    assert estimate_tokens("meter_sale_price") >= 4
    assert estimate_tokens("the cat sat") == 3
    assert estimate_tokens("") == 0
