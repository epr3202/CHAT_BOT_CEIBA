# Build once; promote the resulting immutable image ID (no npm dependencies).
FROM node:22-bookworm-slim
WORKDIR /app/frontend
COPY frontend/ ./
ENV DEPLOYED_RUNTIME=true FRONTEND_HOST=0.0.0.0 FRONTEND_PORT=5173
USER node
ENTRYPOINT ["sh", "-ec", "export DEPLOYED_RUNTIME=true; exec node server.mjs"]
