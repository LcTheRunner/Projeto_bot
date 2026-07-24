#!/bin/sh
set -eu

if [ -z "${DASHBOARD_PASSWORD:-}" ]; then
  echo "DASHBOARD_PASSWORD não configurada" >&2
  exit 1
fi

htpasswd -bc /etc/nginx/.htpasswd "${DASHBOARD_USER:-equipe}" "$DASHBOARD_PASSWORD" >/dev/null
exec nginx -g 'daemon off;'
