# One service: FastAPI serves the simulation API and the web build.
# Large data (fly graph, embeddings) is fetched at first start onto the volume at $FLY_ORACLE_HOME.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
# llama.cpp's prebuilt wheel uses OpenMP.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 \
    FLY_ORACLE_HOME=/data WEB_DIST=/app/web/dist
# Containers see the host's core count. Left alone, OpenBLAS (numpy) and llama.cpp's OpenMP spawn far more
# threads than the CPU quota allows and throttle each other: measured 2.8 s per answer token, 0.06 s with these.
ENV OPENBLAS_NUM_THREADS=1 OMP_WAIT_POLICY=PASSIVE LLM_THREADS=2
WORKDIR /app/inference
COPY inference/pyproject.toml inference/uv.lock inference/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY inference/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/web/dist
CMD ["sh", "-c", "exec .venv/bin/uvicorn fly_oracle_inference.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
