# Embedding + reranking service.
#
# Separate from the API image on purpose. torch is a ~900 MB dependency even in its
# CPU build, and the API container has to start and serve its 27 existing operations
# whether or not the retrieval layer is present or warm. Splitting them also means the
# models load once into a named volume instead of once per API rebuild.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU wheels explicitly. The default PyPI torch wheel carries the CUDA runtime --
# roughly 2.5 GB of libraries that cannot be used on any machine this stack targets.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.6.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# HF_HOME points at the mounted volume so the ~130 MB bi-encoder and ~1.1 GB
# cross-encoder survive a container rebuild.
ENV HF_HOME=/models

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
