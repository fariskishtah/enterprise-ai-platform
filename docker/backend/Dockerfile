FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    HOME=/tmp/app-home

WORKDIR /app

COPY backend/requirements/base.lock ./requirements/base.lock
COPY VERSION ./VERSION
RUN pip install --no-cache-dir --require-hashes -r requirements/base.lock

COPY backend/app ./app

COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data/mlflow /app/data/model-artifacts \
        /app/data/ai-artifacts /app/data/datasets \
    && chown -R 10001:10001 /app/data

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
