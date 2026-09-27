# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/libs/common:/app
WORKDIR /app
COPY libs/common/requirements.txt /libs/common/requirements.txt
COPY services/ai/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r /libs/common/requirements.txt -r requirements.txt
COPY libs/common /libs/common
COPY services/ai/app ./app
COPY services/ai/alembic.ini ./alembic.ini
COPY services/ai/migrations ./migrations
# Migrations run as a separate one-off step (compose command / Container Apps job): alembic upgrade head
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
