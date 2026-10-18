FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_SYNC=1
WORKDIR /app
# Dependencies first (cached layer). The uv download cache is a build cache mount, so it stays out of the image.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev
