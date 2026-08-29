"""Incremental indexing: what gets removed when a source disappears.

One narrow question, and it is the one the indexer got wrong.

`index_corpus.py` walks the corpus file and, for each source in it, reconciles that
source's chunks against the database. A source that disappeared from the corpus
ENTIRELY was therefore never walked, never reconciled, and never deleted -- its chunks
stayed in `doc_chunks` and kept being retrieved.

That was found by m14's prompt-injection test rather than by anything looking for it: a
note was POSTed, indexed, attacked, then DELETEd, and the deleted note was still
answering questions after the next `make index`. `POST /notes` is a public write
endpoint, so a delete that leaves the content live and quotable is a data-deletion
failure, not untidiness. The same hole covered a removed document and an area sheet
dropping below the 10-record floor.

These tests are pure. They need no database, no corpus file and no embedding service --
the decision was extracted from the loop precisely so it could be asserted directly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from index_corpus import sources_to_prune  # noqa: E402


def test_a_source_that_vanished_from_the_corpus_is_pruned():
    indexed = {("note", "144"), ("doc", "docs/a.md")}
    corpus = {("doc", "docs/a.md")}
    assert sources_to_prune(indexed, corpus) == {("note", "144")}


def test_a_source_still_in_the_corpus_is_never_pruned():
    """Pruning is about DISAPPEARANCE, not about change. A source whose chunks all
    changed is reconciled by the per-source loop; touching it here would delete rows the
    loop is about to re-insert."""
    indexed = {("doc", "docs/a.md")}
    corpus = {("doc", "docs/a.md"), ("doc", "docs/b.md")}
    assert sources_to_prune(indexed, corpus) == set()


def test_an_empty_corpus_prunes_nothing():
    """The safety rule, and the reason it exists.

    `build_corpus.py` failing writes a file with no documents. From inside the indexer a
    failed build and a genuinely empty corpus are indistinguishable, and one of the two
    readings deletes the entire index while printing a success line. Refusing is the only
    safe resolution; `--force` remains the way to ask for a full rebuild on purpose.
    """
    indexed = {("doc", "docs/a.md"), ("note", "1"), ("area_sheet", "Dubai Marina")}
    assert sources_to_prune(indexed, set()) == set()


def test_an_empty_index_prunes_nothing_and_does_not_raise():
    assert sources_to_prune(set(), {("doc", "docs/a.md")}) == set()


def test_the_result_is_computed_from_pairs_not_from_ids():
    """`("note", "144")` and `("doc", "144")` are different sources that share an id.
    Comparing on source_id alone would prune one because the other was present."""
    indexed = {("note", "144"), ("doc", "144")}
    corpus = {("doc", "144")}
    assert sources_to_prune(indexed, corpus) == {("note", "144")}
