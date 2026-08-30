"""The voice path, split from the service that runs the models.

    settings.py   the latency budget as data, with the provenance of every target
    pipeline.py   one spoken turn, stage by stage, with the clock on every stage

The models themselves live in `infra/voice/`, a separate container, for the same reason
the embeddings models do: the API must start and serve its 38 operations on a machine that
never runs a model at all, and a rebuild of one image must not re-download the weights of
another.
"""
