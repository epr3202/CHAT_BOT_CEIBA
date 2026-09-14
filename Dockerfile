FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.lock
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
COPY data/ data/
COPY docs/product/ docs/product/
COPY docs/conversation/ docs/conversation/
COPY scripts/*.py scripts/
COPY scripts/protected-entrypoint.sh scripts/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DEPLOYED_RUNTIME=true
RUN groupadd -g 10001 ceiba && useradd -u 10001 -g ceiba -M ceiba
USER 10001:10001
ENTRYPOINT ["sh", "/app/scripts/protected-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
