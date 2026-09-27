# Build context: repository root (see docker-compose.yml)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/libs/common:/app
WORKDIR /app
COPY libs/common/requirements.txt /libs/common/requirements.txt
COPY services/notification/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r /libs/common/requirements.txt -r requirements.txt
COPY libs/common /libs/common
COPY services/notification/app ./app
CMD ["python", "-m", "app.main"]
