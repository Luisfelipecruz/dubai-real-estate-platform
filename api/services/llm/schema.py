"""Pydantic model -> a JSON Schema that constrained decoders will actually accept.

ONE definition of the answer shape, in api/models/ask.py, used for two different jobs:
Pydantic validates what came back, and this turns the same class into the grammar the
model generates under. Hand-maintaining a second copy of the schema is the obvious
alternative and it is the one that silently drifts -- the field gets added to the model,
the grammar keeps rejecting it, and the symptom is a repair loop that never converges.

`model_json_schema()` on its own is not enough, for four reasons that are all about the
consumer rather than about correctness:

  $ref/$defs   Pydantic factors nested models into `$defs` and points at them. Every
               constrained decoder has to resolve those into a grammar, and support
               ranges from complete to absent depending on the runtime. Inlining costs
               a few duplicated bytes and removes the whole question.
  required     JSON Schema treats a field with a default as optional. OpenAI-style
               `strict: true` requires every property to be listed in `required`, and a
               nullable field carrying `null` says more than an absent one anyway: the
               model asserting `unanswerable_reason: null` is a claim, and a missing key
               is silence.
  additionalProperties
               Absent means "anything else is allowed". Under strict decoding it must be
               false, and it should be false regardless -- an extra key in a grounded
               answer is a field somebody meant to add to the model and did not.
  anyOf-null   `str | None` becomes `anyOf: [{string}, {null}]`. The equivalent
               `{"type": ["string", "null"]}` is understood by strictly more decoders,
               and it is the same schema.

`title` and `default` are dropped as well. They carry no constraint and every token in
the grammar is a token the sampler has to be steered around.
"""

from typing import Any


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """Resolve $ref against $defs, recursively, and strip decorative keys."""
    if isinstance(node, list):
        return [_inline(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        # Only local #/$defs/Name references exist here; Pydantic emits nothing else for
        # a self-contained model tree. A remote $ref would be a different problem and is
        # deliberately not handled rather than half-handled.
        name = node["$ref"].rsplit("/", 1)[-1]
        if name not in defs:
            raise KeyError(f"unresolvable $ref {node['$ref']!r}")
        merged = _inline(defs[name], defs)
        # Sibling keys alongside a $ref (description, etc.) win over the target's.
        extra = {k: v for k, v in node.items() if k != "$ref"}
        return {**merged, **_inline(extra, defs)} if extra else merged

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("title", "default", "$defs"):
            continue
        out[key] = _inline(value, defs)

    # anyOf: [{"type": "X"}, {"type": "null"}]  ->  {"type": ["X", "null"]}
    any_of = out.get("anyOf")
    if (
        isinstance(any_of, list)
        and len(any_of) == 2
        and all(isinstance(b, dict) and set(b) == {"type"} for b in any_of)
        and any(b["type"] == "null" for b in any_of)
    ):
        non_null = next(b["type"] for b in any_of if b["type"] != "null")
        out.pop("anyOf")
        out["type"] = [non_null, "null"]

    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"].keys())

    return out


def strict_json_schema(model: type) -> dict[str, Any]:
    """A self-contained, strict-mode JSON Schema for a Pydantic model."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return _inline(raw, defs)
