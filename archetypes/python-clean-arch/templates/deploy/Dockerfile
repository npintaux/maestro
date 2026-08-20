# Multi-stage secure distroless container for Cloud Run deployment
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r <(uv pip compile pyproject.toml)

COPY src/ ./src/

# Final production distroless image
FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /app /app

ENV PYTHONPATH=/usr/local/lib/python3.12/site-packages:/app \
    PORT=8080

EXPOSE 8080

USER nonroot:nonroot

ENTRYPOINT ["python3", "-m", "uvicorn", "src.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8080"]
