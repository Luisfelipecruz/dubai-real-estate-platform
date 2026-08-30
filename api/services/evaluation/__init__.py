"""Grading, as library code rather than as a script.

m15 shipped `scripts/run_routing_eval.py` with its grader inlined, which was right at the
time: there was one fixture, one caller and one question being asked. m16 has three
fixtures and two runners, and the moment a grader has two callers it needs a test of its
own — every grading bug this project has found so far was found by reading output by
hand, and two of them (the ASCII apostrophe, the marker matching in the second sentence)
would have been caught in seconds by a unit test.

So the graders live here, under pytest, and the scripts in `scripts/` are transport:
they issue HTTP requests, print a table, and exit non-zero. Nothing in `scripts/` decides
whether an answer is right.

    numeric.py     pulling candidate numbers out of prose, and comparing them
    truth.py       running a fixture's ground-truth SQL, read-only, against raw tables
    grading.py     the verdict for one answer, including the decoy check
    retrieval.py   recall@k, MRR and nDCG@5 over a ranked list of source ids
"""
