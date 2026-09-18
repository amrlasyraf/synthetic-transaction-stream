FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && groupadd --gid 10001 stream \
    && useradd --uid 10001 --gid stream --no-create-home stream \
    && mkdir /data \
    && chown stream:stream /data

USER stream
EXPOSE 8080
CMD ["python", "-m", "synthetic_transaction_stream.live", "--host", "0.0.0.0", "--port", "8080", "--db", "/data/events.sqlite"]
