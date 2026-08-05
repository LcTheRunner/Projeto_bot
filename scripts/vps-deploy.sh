#!/bin/sh
set -eu

# Deploy de baixo consumo para a VPS.
# Remove apenas imagens sem tag e cache de build não utilizado. Volumes e o
# banco MariaDB nunca são removidos por este script.

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
CACHE_LIMIT="${BUILDER_CACHE_MAX:-}"

echo "Uso de disco antes do deploy:"
docker system df

docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

# Builds sucessivos deixam imagens antigas sem tag e cache intermediário de
# npm/Python. A poda abaixo preserva imagens em uso e todos os volumes.
docker image rm cadu-api:latest cadu-worker:latest 2>/dev/null || true
docker image prune -f
if [ -n "$CACHE_LIMIT" ]; then
  docker buildx prune -af --max-used-space "$CACHE_LIMIT"
else
  docker buildx prune -af
fi

echo "Uso de disco depois do deploy:"
docker system df
