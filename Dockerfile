FROM python:3.12-slim

WORKDIR /app

# psycopg2 intentionally omitted: PG (cliproxyapi) decommissioned with aeza
# (TASK-cliproxy-decommission); app.py tolerates missing psycopg2 with a warning.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY app.py /app/app.py
COPY static /app/static

# static lives in image; data stays on host bind mount
ENV USAGE_STATIC_DIR=/app/static

# uvicorn direct (app.py __main__ binds 127.0.0.1 — unusable inside docker bridge)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3210"]
