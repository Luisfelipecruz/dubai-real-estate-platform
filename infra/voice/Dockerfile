# Voice service: VAD, speech-to-text, text-to-speech.
#
# Separate from both the API image and the embeddings image, for the same reason those two
# are separate from each other: the API must start and serve its 38 operations whether or
# not any model is present, and a rebuild of one must not re-download the weights of
# another.
#
# NOTHING HERE PULLS TORCH, and that is deliberate rather than incidental. The embeddings
# service already carries a ~900 MB CPU torch build for the bi-encoder and cross-encoder.
# This image uses CTranslate2 for Whisper and ONNX Runtime for Piper, so the whole thing is
# a fraction of that — which matters because every stage in it has a target measured in
# hundreds of milliseconds and a cold start measured in minutes is what the embeddings
# service already taught this project to avoid.
#
# No compiler either. `webrtcvad-wheels` ships prebuilt wheels; the original `webrtcvad`
# would need gcc AND a `setuptools<81` pin. See requirements.txt.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# The same named volume the embeddings service uses. Whisper base.en int8 is ~150 MB and a
# Piper voice is ~60 MB; both must survive a rebuild and neither may land in the working
# tree. HF_HOME covers the Whisper download; PIPER_DATA_DIR covers the voice.
ENV HF_HOME=/models \
    PIPER_DATA_DIR=/models/piper

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8200"]
