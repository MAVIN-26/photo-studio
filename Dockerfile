FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --system app \
    && useradd --system --gid app app

COPY backend/ ./
COPY frontend/ /app/frontend/

USER app
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER app
CMD ["pytest", "-p", "no:cacheprovider"]
