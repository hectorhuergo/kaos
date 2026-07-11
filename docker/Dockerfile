# KAOS application image — runs the CLI (scheduler, dashboard, …).
#
# Kept minimal: install the project (with the extras the runtime uses) and hand
# control to the `kaos` console script. Compose services choose the command
# (e.g. `kaos schedule`, `kaos serve`). Build context is the repo root:
#   docker compose --profile app build
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (better layer caching), then the package itself.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[discord,postgres,dashboard]"

# Default: run the periodic scheduler. Compose can override the command.
ENTRYPOINT ["kaos"]
CMD ["schedule"]

