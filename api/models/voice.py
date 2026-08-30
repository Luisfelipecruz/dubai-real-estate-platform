"""Request and response shapes for the voice path.

The response is a LATENCY REPORT that happens to contain an answer, which is the inversion
this milestone is for. `/ask` and `/agent/query` return an answer with timings attached;
here the timings are the product. §7.2 states an 800 ms budget and a stage table adding to
~1,320 ms, and the measurements this project already has say the real figure is an order of
magnitude worse than that. A response body that made the answer prominent and the numbers
incidental would be the wrong shape for the only question worth asking.
"""

from pydantic import BaseModel, Field

__all__ = ["StageBudget", "TurnRequest", "TurnResponse", "BudgetResponse"]


class TurnRequest(BaseModel):
    """Everything except the audio, which arrives as the raw body.

    Audio is not in this model on purpose. Base64 in a JSON envelope inflates the payload
    by a third and puts a decode step in a path measured in hundreds of milliseconds, so
    `POST /voice/turn` takes raw PCM as its body and these as query parameters.
    """

    route: str = Field(
        "ask",
        description="ask | agent. `ask` by default because M-48 measured an agent run at "
        "1.4-58.6 s per question, and the handoff's standing rule is that a multi-step "
        "agent run does not belong in an interactive path. `agent` is available so the "
        "cost of putting it there can be MEASURED rather than argued.",
    )
    trailing_silence_ms: int = Field(200, ge=40, le=2000)
    beam_size: int = Field(
        1,
        ge=1,
        le=5,
        description="Greedy by default. Beam search is the library default at 5 and was "
        "measured here at 346-412 ms against 329-352 ms greedy, for an identical "
        "transcript on the golden question.",
    )
    speak: bool = Field(True, description="Set false to measure the pipeline without TTS.")


class StageBudget(BaseModel):
    stage: str
    target_ms: int
    measured_ms: float | None = Field(
        None,
        description="null, not 0, when the stage did not run. `$0.00` and `null` are "
        "different facts in this repository and so are milliseconds.",
    )
    over_by_ms: float | None = None
    within_target: bool | None = None
    source: str = Field(description="Where the target came from — a measurement or a plan.")


class TurnResponse(BaseModel):
    transcript: str
    answer: str
    answered: bool
    route: str
    spoken_first: str = Field(
        description="The clause actually synthesised. §7.2's third lever: perceived "
        "latency is time to FIRST audio, so the opening sentence is spoken while the "
        "rest would still be streaming."
    )
    stages_ms: dict[str, float]
    budget: list[StageBudget]
    to_first_audio_ms: float = Field(
        description="Endpoint to first PCM sample. The headline number. EXCLUDES the VAD "
        "stage: the budget clock starts when the speaker stops, and endpointing is what "
        "decides that they have."
    )
    total_ms: float
    budget_ms: int
    within_budget: bool
    over_budget_by_ms: float
    audio_bytes: int
    audio_ms: int
    sample_rate: int = Field(
        description="The VOICE's native rate, not the input rate. Input to VAD and STT is "
        "16 kHz because webrtcvad accepts nothing else; Piper's medium voices emit "
        "22.05 kHz. Resampling in the interactive path would cost latency to satisfy a "
        "symmetry nothing needs, so the rate is reported instead."
    )
    stt_realtime_factor: float
    endpoint_ms: int | None
    warnings: list[str] = Field(
        default_factory=list,
        description="Cold models, missing endpoints, unsynthesised remainder. A timing "
        "taken through a cold model is not comparable with a warm one and says so here "
        "rather than in a footnote.",
    )


class BudgetResponse(BaseModel):
    budget_ms: int
    target_total_ms: int
    stages: list[StageBudget]
    verdict: str
    rerank_on_voice_path: bool = Field(
        description="False, and NOT as a latency sacrifice. m16 measured the "
        "cross-encoder at 8/20 top-1 against dense's 17/20 on the golden set while "
        "costing 2.9 s. It loses on both axes, so skipping it is free."
    )
    measured: dict = Field(
        default_factory=dict,
        description="The last measured figures per stage, or empty if nothing has run.",
    )
