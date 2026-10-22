FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.33 /uv /uvx /bin/
WORKDIR /app
COPY . .
RUN uv sync --locked --no-dev
ENTRYPOINT ["uv", "run", "gauntlet"]
CMD ["--help"]
