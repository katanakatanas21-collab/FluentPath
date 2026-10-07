# Single-stage image for the FastAPI backend.
#
# One stage on purpose: the runtime dependencies are fully pinned in
# requirements.txt, so a builder stage would add a second artifact to reason
# about without changing what ships.
#
# python:3.14-slim matches the interpreter this project is developed and tested
# against (CPython 3.14). Do not drift the base version without re-running the
# backend suite, because the pinned wheels are resolved for this interpreter.

FROM python:3.14-slim

# Unbuffered output so container logs are readable in real time rather than in
# 8 KB blocks, and .pyc writing off so the image carries no build artifacts.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when the pins change, not on
# every source edit.
COPY requirements.txt ./
RUN python -m pip install -r requirements.txt

# Application source only. .dockerignore keeps data/, .env, the virtualenv,
# tests and QA artifacts out of this layer, so the copy is the deployment
# surface and nothing else.
COPY server.py ai_teacher.py zoom_service.py db_config.py ./
COPY persistence/ ./persistence/
COPY db/ ./db/
COPY security/ ./security/
COPY migrations/ ./migrations/
COPY alembic.ini ./

# Run as an unprivileged user. The account exists only to own the source tree it
# reads; nothing in the image requires root to serve traffic.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The port is fixed so the effective start command below cannot be overridden
# into a different listening port by a stray environment value. Workers stay at
# exactly 1: the process holds a single PostgreSQL engine and a JSON file
# bridge, so extra workers would mean duplicate connections without extra
# throughput.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]