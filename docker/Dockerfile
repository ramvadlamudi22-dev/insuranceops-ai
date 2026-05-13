# Stage 1: Builder
FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -e ".[dev]"
COPY src/ src/
COPY migrations/ migrations/

# Stage 2: Runtime
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src ./src
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/pyproject.toml ./
RUN useradd -r -s /bin/false appuser && mkdir -p /data/payloads && chown appuser:appuser /data/payloads
USER appuser
EXPOSE 8000
ENV PYTHONPATH=/app/src
# Default CMD is api; override to "python -m insuranceops.workers.main" for worker
CMD ["uvicorn", "insuranceops.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
