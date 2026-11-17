FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    DELIVERY_DB=/app/data/delivery.db \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[groq]"

RUN analista-sql gerar-dados --saida /app/data/delivery.db

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["sh", "-c", "analista-sql web --host 0.0.0.0 --porta ${PORT:-8000} --provedor auto"]
