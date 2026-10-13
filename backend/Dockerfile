FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY synthbody ./synthbody
COPY scripts ./scripts
COPY tests ./tests
COPY pyproject.toml alembic.ini ./

# Database lives on a volume so stored runs survive a rebuild.
ENV SYNTHBODY_DATABASE_URL=sqlite:////data/synthbody.db
RUN mkdir -p /data

EXPOSE 8011

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if 'SYNTHBODY' in urllib.request.urlopen('http://127.0.0.1:8011/health',timeout=4).read().decode() else 1)"

CMD ["python", "-m", "uvicorn", "synthbody.api.main:app", "--host", "0.0.0.0", "--port", "8011"]
