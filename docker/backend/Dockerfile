FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/app-home

WORKDIR /app

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/requirements ./requirements
COPY backend/app ./app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements/base.txt

COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data/mlflow /app/data/model-artifacts /app/data/ai-artifacts \
    && chown -R 10001:10001 /app/data

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
