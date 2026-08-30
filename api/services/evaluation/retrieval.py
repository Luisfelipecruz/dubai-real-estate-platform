"""Rank metrics over a ranked list of source ids.

WHY SOURCE IDS AND NOT CHUNK IDS
---------------------------------
`eval/golden/retrieval.yaml` grades per `source_id` and its header explains why: chunk
boundaries move whenever the chunker changes, document identity does not, and a fixture
that must be regenerated after every chunker tweak is a fixture nobody maintains. That
decision was made in m13a and this module inherits it. One consequence has to be stated
rather than assumed: a document that produced three chunks in the top 5 occupies three
slots, and its rank is the FIRST of them. `hit@k` and `MRR` are therefore taken on the RAW
chunk list — deduplicating would promote a relevant document past another document's
repeats and flatter both — while `nDCG@5` is computed over DISTINCT documents, because its
denominator is an ideal ordering of the graded set and a ranking with repeats is not a
permutation of that. Mixing the two conventions in one table is why both are stated here
and again at each computation. `duplicate_slots` reports the difference.

WHAT `hit@k` AND `recall@k` MEAN HERE, BECAUSE THEY ARE NOT THE SAME
---------------------------------------------------------------------
m13a reported "recall@5 9/10" and it meant *nine of ten questions had a relevant document
somewhere in the top 5* — a per-question hit rate, which the literature usually calls
success@k. That is the number the m13a write-up, the changelog and M-12 all quote, so it
keeps its meaning and gets its proper name here: `hit_at_k`. `recall_at_k` is computed
separately and is the fraction of a question's graded-relevant documents that appear.
They diverge for exactly the questions with more than one acceptable document, which is
most of them, and quoting one while meaning the other would silently restate a published
figure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["QuestionScores", "score_question", "aggregate"]

# A document graded 2 (answers the question, less directly) or 3 (ideal) counts as
# relevant. 1 is "same subject, does not answer it" and 0 is an explicit decoy — a
# document that LOOKS retrievable and is wrong. Counting 1s as relevant would score a
# retriever for returning topically adjacent prose, which is the failure mode the 0-3
# scale was introduced to make visible.
RELEVANT_FLOOR = 2
IDEAL = 3


@dataclass
class QuestionScores:
    id: str
    ranked: list[str]
    grades: dict[str, int]
    top1_ideal: bool = False
    hit_at: dict[int, bool] = field(default_factory=dict)
    recall_at: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    decoys_above_answer: list[str] = field(default_factory=list)
    decoy_at_top: str | None = None
    duplicate_slots: int = 0


def _dcg(gains: list[int]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def score_question(
    question_id: str,
    ranked_sources: list[str],
    relevance: dict[str, int],
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> QuestionScores:
    """Score one question's ranked result list against its graded relevance map.

    A source not named in the fixture is graded 0 — unjudged, not irrelevant, and the
    distinction matters for nDCG. With a hand-labelled fixture of this size the pool is
    shallow: a genuinely good document nobody thought to grade is scored as worthless.
    That biases every metric here DOWNWARD, which is the safe direction for a regression
    gate and the wrong direction for a headline number. The write-up says so.
    """
    grades = {s: relevance.get(s, 0) for s in ranked_sources}
    relevant = {s for s, g in relevance.items() if g >= RELEVANT_FLOOR}

    scores = QuestionScores(id=question_id, ranked=ranked_sources, grades=grades)
    scores.duplicate_slots = len(ranked_sources) - len(set(ranked_sources))

    if ranked_sources:
        scores.top1_ideal = relevance.get(ranked_sources[0], 0) >= IDEAL
        # A document the fixture explicitly graded 0 sitting at rank 1 is the sharpest
        # single signal a retrieval run produces, and `decoys_above_answer` misses it
        # whenever NO relevant document appears at all — there is then nothing for the
        # decoy to be "above". That is precisely the worst case, and it was invisible
        # until a write-up of this milestone became a decoy for one of its own questions.
        if relevance.get(ranked_sources[0]) == 0:
            scores.decoy_at_top = ranked_sources[0]

    for k in ks:
        window = ranked_sources[:k]
        scores.hit_at[k] = any(relevance.get(s, 0) >= RELEVANT_FLOOR for s in window)
        scores.recall_at[k] = (
            len({s for s in window if s in relevant}) / len(relevant) if relevant else 0.0
        )

    for rank, source in enumerate(ranked_sources, start=1):
        if relevance.get(source, 0) >= RELEVANT_FLOOR:
            scores.mrr = 1.0 / rank
            # Everything the fixture explicitly graded 0 that outranked the first real
            # answer. This is the number a nearest-neighbour list should be judged on and
            # the one an average recall hides: G-10's dense arm put the decoy first every
            # time and still scored a hit@5.
            scores.decoys_above_answer = [
                s for s in ranked_sources[: rank - 1] if relevance.get(s) == 0
            ]
            break

    # nDCG IS COMPUTED OVER DISTINCT DOCUMENTS. The other metrics are not, and the split
    # is deliberate rather than sloppy.
    #
    # The first run of this module reported nDCG@5 = 2.436, which is impossible: the
    # measure is a ratio bounded at 1. The cause is that this fixture grades DOCUMENTS
    # while `/search` ranks CHUNKS, so one document can occupy three of the top five slots
    # and contribute its gain three times — against an ideal DCG built from each graded
    # document once. The numerator counted repeats and the denominator did not.
    #
    # nDCG's definition requires the ideal ordering to be a permutation of the ranking
    # being scored, so for THIS measure the ranking has to be deduplicated to the unit the
    # fixture grades. First occurrence wins, which is also the rank a reader experiences.
    #
    # `hit_at` and `mrr` above stay on the RAW chunk list on purpose. They ask how far
    # down the results a relevant document first appears, which is a question about what
    # the user scrolls past, and deduplicating would flatter it — a relevant document at
    # chunk rank 3 behind two chunks of one other document would be promoted to rank 2.
    # It is also the convention the published m13a figures were measured under, and those
    # reproduce exactly under it.
    #
    # `duplicate_slots` is reported so the difference between the two views is visible
    # rather than implied.
    seen: list[str] = []
    for source in ranked_sources:
        if source not in seen:
            seen.append(source)
    gains = [relevance.get(s, 0) for s in seen[:5]]
    ideal_gains = sorted(relevance.values(), reverse=True)[:5]
    ideal = _dcg(ideal_gains)
    scores.ndcg_at_5 = (_dcg(gains) / ideal) if ideal else 0.0
    return scores


def aggregate(scored: list[QuestionScores], ks: tuple[int, ...] = (1, 3, 5, 10)) -> dict:
    """Mean of each metric over the questions, plus the counts behind them.

    Counts travel with the means because a mean over ten questions is two significant
    figures pretending to be four, and because "8/10" is a sentence a reader can check
    while "0.8" is one they have to trust.
    """
    n = len(scored)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "top1_ideal": sum(s.top1_ideal for s in scored) / n,
        "top1_ideal_count": sum(s.top1_ideal for s in scored),
        "hit_at": {k: sum(s.hit_at.get(k, False) for s in scored) / n for k in ks},
        "hit_at_count": {k: sum(s.hit_at.get(k, False) for s in scored) for k in ks},
        "recall_at": {k: sum(s.recall_at.get(k, 0.0) for s in scored) / n for k in ks},
        "mrr": sum(s.mrr for s in scored) / n,
        "ndcg_at_5": sum(s.ndcg_at_5 for s in scored) / n,
        "questions_with_a_decoy_above_the_answer": sum(
            1 for s in scored if s.decoys_above_answer
        ),
        "questions_with_a_decoy_at_rank_1": sum(1 for s in scored if s.decoy_at_top),
    }
