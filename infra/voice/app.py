"""Voice service: endpointing, speech-to-text, text-to-speech.

Three stages, one container, and every response carries its own stage timing. That is not
instrumentation added afterwards — it is the reason the service exists. The plan gives this
pipeline an **800 ms** end-to-end budget and the measurements already in this project say
the budget cannot be met: `/ask` generation alone is 7.9–20.9 s p50 (M-21, M-22) and an
agent run is 1.4–58.6 s (M-48). The useful output of m17 is therefore a *measured* budget
with a stage-by-stage account of where the time goes, not a demo that hides it.

THE AUDIO CONTRACT, STATED ONCE
--------------------------------
Every endpoint here speaks **16 kHz, mono, signed 16-bit little-endian PCM**, raw, with no
container and no header. One format everywhere, chosen because it is what `webrtcvad`
requires and what `faster-whisper` wants anyway, so nothing in the interactive path spends
time resampling. A WAV header would be 44 bytes and one more thing to get wrong.

WHY THE MODELS LOAD LAZILY
---------------------------
Same reason as the embeddings service, and this project has already paid for it once: the
cross-encoder is 1.1 GB and loads on first call, so the first `/search?rerank=true` after a
cold start took ~11 minutes against a 30 s client timeout and looked exactly like a crash.
`/health` answers immediately and reports which models are actually resident, so a
healthcheck cannot mistake a download for a failure — and so a latency measurement cannot
accidentally include one.
"""

import io
import os
import time
import wave

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base.en")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
PIPER_VOICE = os.getenv("PIPER_VOICE", "en_US-lessac-medium")
PIPER_DATA_DIR = os.getenv("PIPER_DATA_DIR", "/models/piper")

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # s16le

# webrtcvad accepts 10, 20 or 30 ms frames and nothing else. 20 ms is the middle option and
# the one the transport already uses for Opus, so the same framing serves both.
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * SAMPLE_WIDTH * FRAME_MS // 1000

_whisper = None
_piper = None

app = FastAPI(title="Voice", version="0.1.0")


def get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE)
    return _whisper


def get_piper():
    """Load the Piper voice, downloading it once into the shared model volume.

    `piper-tts` will not fetch a voice for you, so the download is explicit. It goes to
    PIPER_DATA_DIR, which is inside the same named volume the embeddings weights use, for
    the reason that volume exists: ~60 MB that must survive a rebuild and must never appear
    in a `git status`.
    """
    global _piper
    if _piper is None:
        from huggingface_hub import hf_hub_download
        from piper import PiperVoice

        os.makedirs(PIPER_DATA_DIR, exist_ok=True)
        # rhasspy/piper-voices lays voices out as <lang>/<locale>/<name>/<quality>/.
        locale, name, quality = PIPER_VOICE.split("-")[0], PIPER_VOICE.split("-")[1], PIPER_VOICE.split("-")[2]
        prefix = f"{locale.split('_')[0]}/{locale}/{name}/{quality}/{PIPER_VOICE}"
        paths = [
            hf_hub_download("rhasspy/piper-voices", f"{prefix}.onnx",
                            local_dir=PIPER_DATA_DIR),
            hf_hub_download("rhasspy/piper-voices", f"{prefix}.onnx.json",
                            local_dir=PIPER_DATA_DIR),
        ]
        _piper = PiperVoice.load(paths[0], config_path=paths[1])
    return _piper


# ── health ──────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    """Answers before anything is loaded, and says what is resident.

    `ready` is per model rather than one boolean, because the three stages fail
    independently and a caller measuring a latency budget needs to know which of them is
    about to pay a cold-start cost. A single `ready: false` would hide that.
    """
    return {
        "status": "ok",
        "sample_rate": SAMPLE_RATE,
        "frame_ms": FRAME_MS,
        "models": {
            "stt": {"name": WHISPER_MODEL, "compute": WHISPER_COMPUTE,
                    "resident": _whisper is not None},
            "tts": {"name": PIPER_VOICE, "resident": _piper is not None},
            "vad": {"name": "webrtcvad-wheels", "resident": True},
        },
    }


# ── VAD / endpointing ───────────────────────────────────────────────────────


class VadRequest(BaseModel):
    aggressiveness: int = Field(2, ge=0, le=3)
    trailing_silence_ms: int = Field(
        200, ge=40,
        description="Silence after speech before the turn is considered over. The plan's "
                    "200 ms target, and the single biggest lever in the budget.",
    )


class VadResult(BaseModel):
    frames: int
    speech_frames: int
    speech_ratio: float
    endpoint_ms: int | None = Field(
        None,
        description="Offset at which the turn ended, or null if the speaker had not "
                    "finished by the end of the audio. NULL IS NOT AN ERROR: it is the "
                    "normal state mid-utterance and the caller must keep streaming.",
    )
    took_ms: float


@app.post("/vad", response_model=VadResult)
async def vad(request: Request, aggressiveness: int = 2, trailing_silence_ms: int = 200):
    """Where does this utterance end?

    Endpointing is the biggest single lever in an 800 ms budget and the easiest to
    over-tune: shorten the trailing-silence threshold and the turn starts sooner but clips
    a speaker who pauses mid-sentence, which costs a whole extra turn rather than 100 ms.
    So the threshold is a parameter, it is reported back, and `docs/voice-latency.md`
    measures the trade rather than asserting a value.
    """
    import webrtcvad

    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty body; expected raw 16 kHz mono s16le PCM")

    started = time.perf_counter()
    detector = webrtcvad.Vad(aggressiveness)
    needed = int(trailing_silence_ms / FRAME_MS)

    total = speech = trailing = 0
    endpoint_ms = None
    seen_speech = False
    for offset in range(0, len(audio) - FRAME_BYTES + 1, FRAME_BYTES):
        frame = audio[offset : offset + FRAME_BYTES]
        total += 1
        if detector.is_speech(frame, SAMPLE_RATE):
            speech += 1
            seen_speech = True
            trailing = 0
        elif seen_speech:
            trailing += 1
            if endpoint_ms is None and trailing >= needed:
                # The endpoint is where the SILENCE began, not where it was confirmed.
                # Reporting the confirmation point would fold the threshold into the
                # measurement and make every threshold look equally good.
                endpoint_ms = (total - trailing) * FRAME_MS

    return VadResult(
        frames=total,
        speech_frames=speech,
        speech_ratio=round(speech / total, 4) if total else 0.0,
        endpoint_ms=endpoint_ms,
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# ── speech to text ──────────────────────────────────────────────────────────


class SttResult(BaseModel):
    text: str
    language: str
    audio_ms: int
    took_ms: float
    realtime_factor: float = Field(
        description="took_ms / audio_ms. Below 1.0 means faster than real time, which is "
                    "the only version of this number that can ever fit in a live budget."
    )
    model: str
    cold: bool = Field(description="True if this call paid the model load.")


@app.post("/stt", response_model=SttResult)
async def stt(request: Request, beam_size: int = 1):
    """Transcribe raw PCM.

    `beam_size` defaults to 1 — greedy — rather than the library default of 5. Beam search
    buys accuracy that a five-word property question does not need and costs latency the
    budget cannot spare. It is a parameter so the trade can be measured rather than
    asserted, which is what §7.2 asks for.
    """
    import numpy as np

    audio = await request.body()
    if not audio:
        raise HTTPException(400, "empty body; expected raw 16 kHz mono s16le PCM")

    cold = _whisper is None
    model = get_whisper()
    samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0

    started = time.perf_counter()
    segments, info = model.transcribe(samples, beam_size=beam_size, language="en")
    text = "".join(segment.text for segment in segments).strip()
    took = (time.perf_counter() - started) * 1000

    audio_ms = int(len(samples) / SAMPLE_RATE * 1000)
    return SttResult(
        text=text,
        language=info.language,
        audio_ms=audio_ms,
        took_ms=round(took, 2),
        realtime_factor=round(took / audio_ms, 4) if audio_ms else 0.0,
        model=WHISPER_MODEL,
        cold=cold,
    )


# ── text to speech ──────────────────────────────────────────────────────────


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    wav: bool = Field(
        False,
        description="Wrap the PCM in a WAV header. Off by default: the transport streams "
                    "raw frames and a header in the middle of a stream is corruption.",
    )


@app.post("/tts")
async def tts(body: TtsRequest):
    """Synthesise speech, and report time to the FIRST audio rather than to the last.

    Perceived latency in a spoken turn is time-to-first-audio. A caller that waits for a
    complete utterance before playing anything has converted a streaming system into a
    batch one and will measure a number three times worse than the one the listener
    experiences. `first_chunk_ms` is the number that belongs in the budget;
    `took_ms` is what it cost in total, reported so the difference is visible.
    """
    cold = _piper is None
    voice = get_piper()

    started = time.perf_counter()
    first_chunk_ms = None
    chunks: list[bytes] = []
    for chunk in voice.synthesize(body.text):
        if first_chunk_ms is None:
            first_chunk_ms = (time.perf_counter() - started) * 1000
        chunks.append(chunk.audio_int16_bytes)
    pcm = b"".join(chunks)
    took = (time.perf_counter() - started) * 1000

    rate = getattr(voice.config, "sample_rate", SAMPLE_RATE)
    payload = pcm
    if body.wav:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(rate)
            handle.writeframes(pcm)
        payload = buffer.getvalue()

    from fastapi.responses import Response

    audio_ms = int(len(pcm) / SAMPLE_WIDTH / rate * 1000)
    return Response(
        content=payload,
        media_type="audio/wav" if body.wav else "application/octet-stream",
        headers={
            # Timings ride in headers because the body is audio. A JSON envelope with
            # base64 audio would inflate the payload by a third and put a decode step in
            # the interactive path.
            "X-Took-Ms": f"{took:.2f}",
            "X-First-Chunk-Ms": f"{first_chunk_ms or 0:.2f}",
            "X-Audio-Ms": str(audio_ms),
            "X-Sample-Rate": str(rate),
            "X-Voice": PIPER_VOICE,
            "X-Cold": str(cold).lower(),
        },
    )
