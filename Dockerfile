# Imagem de produção do ExataMed.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EXATAMED_ENV=production \
    PORT=8000

WORKDIR /app

# Dependências com versões travadas (build reproduzível).
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY exatamed ./exatamed
COPY docs ./docs

# Executa sem privilégios de root.
RUN useradd --system --uid 10001 --home /app exatamed && mkdir -p /app/instance && chown -R exatamed /app/instance
USER exatamed

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/saude', timeout=4)"

# --preload: cria o esquema e sela a cadeia de auditoria uma única vez, antes dos workers.
CMD ["sh", "-c", "exec gunicorn --preload --workers ${WEB_CONCURRENCY:-2} --bind 0.0.0.0:${PORT} 'exatamed:create_app()'"]
