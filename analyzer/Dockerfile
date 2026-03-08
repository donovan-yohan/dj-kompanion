FROM python:3.11-slim

WORKDIR /app

# System deps for audio processing and building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (pin torch 2.5.1 CPU for NATTEN wheel compatibility)
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.5.1+cpu torchaudio==2.5.1+cpu \
    --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Install NATTEN CPU wheel (must match torch version; --trusted-host for expired cert)
RUN pip install --no-cache-dir \
    natten==0.17.5+torch250cpu \
    -f https://whl.natten.org && \
    # Patch NATTEN to not call torch.cuda.get_device_capability on CPU-only torch
    sed -i 's/get_device_cc() >= 70/False/g' \
        /usr/local/lib/python3.11/site-packages/natten/utils/testing.py

# Install madmom from vendored source (broken on pip release for Python 3.11+)
COPY vendor/madmom /tmp/madmom
RUN pip install --no-cache-dir Cython numpy && \
    pip install --no-cache-dir /tmp/madmom && \
    rm -rf /tmp/madmom

# Install allin1 from vendored source (without its torch dep since we pinned it above)
COPY vendor/all-in-one /tmp/all-in-one
RUN pip install --no-cache-dir --no-deps /tmp/all-in-one && \
    pip install --no-cache-dir librosa demucs hydra-core omegaconf huggingface_hub matplotlib && \
    rm -rf /tmp/all-in-one

# Copy analyzer code as a proper Python package
COPY . ./analyzer/

EXPOSE 9235

CMD ["uvicorn", "analyzer.app:app", "--host", "0.0.0.0", "--port", "9235"]
