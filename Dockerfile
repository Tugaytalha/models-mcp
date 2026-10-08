FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml alembic.ini ./
COPY src ./src
RUN pip install .

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER 10001

EXPOSE 8000
# Şema migration'ı uygulama açılışında otomatik çalışır (Postgres advisory lock ile çoklu replica güvenli).
# Kapatmak için CATALOG_AUTO_MIGRATE=false.
CMD ["uvicorn", "models_catalog.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
