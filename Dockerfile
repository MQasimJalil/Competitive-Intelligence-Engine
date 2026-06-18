FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./

RUN touch README.md \
    && python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev]" \
    && python -m playwright install --with-deps chromium

COPY README.md ./
COPY app ./app
COPY static ./static
COPY templates ./templates
COPY scripts ./scripts
COPY tests ./tests
COPY benchmarks ./benchmarks

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
