FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi "uvicorn[standard]"

COPY app.py /app/app.py
COPY static /app/static

# static lives in image; data stays on host bind mount
ENV USAGE_STATIC_DIR=/app/static

CMD ["python", "/app/app.py"]
