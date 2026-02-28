FROM python:3.11-slim

WORKDIR /app

# System deps for audio processing and building native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install madmom from git (broken on pip release for Python 3.11+)
RUN pip install --no-cache-dir Cython numpy && \
    pip install --no-cache-dir git+https://github.com/CPJKU/madmom.git

# Install allin1 from git (needs NATTEN which works on Linux)
RUN pip install --no-cache-dir git+https://github.com/hordiales/all-in-one.git

# Copy analyzer code
COPY . .

EXPOSE 9235

CMD ["uvicorn", "analyzer.app:app", "--host", "0.0.0.0", "--port", "9235"]
