FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=9000 \
    AUDIOSOCKET_PORT=9092

COPY pyproject.toml README.md run.py ./
COPY src ./src

RUN pip install --no-cache-dir -e . && \
    mkdir -p /app/storage/recordings /app/storage/voices

EXPOSE 9000 9092

CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "9000"]
