"""Agent orchestration: tools, the loop, and the accounting that makes it auditable.

Three modules, and the split follows what can be tested without the next one:

    settings.py  budgets, each derived from something m14 measured
    tools.py     what the agent can do, and the descriptions that route it there
    executor.py  the loop, the recovery table, and the per-step accounting

`tools.py` is testable with no model at all -- every handler is an async function over a
database connection -- and `executor.py` is testable with a scripted provider. Only the
end-to-end run needs a 20B model on the host, which is why the fast tests stay fast.
"""
