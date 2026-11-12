#!/usr/bin/env bash
# Use a fresh, disposable Compose project. The fixture survives a container recreation.
set -euo pipefail

: "${COMPOSE_PROJECT_NAME:?Use a unique disposable Compose project}"
if [[ -n "$(docker compose ps --all --quiet db)" ]] ||
   docker volume inspect "${COMPOSE_PROJECT_NAME}_postgres-data" >/dev/null 2>&1; then
    echo 'The smoke check requires an unused Compose project.' >&2
    exit 1
fi

docker compose up -d --wait --wait-timeout 120 db
db_id=$(docker compose ps --quiet db)
test "$(docker inspect --format '{{.State.Health.Status}}' "$db_id")" = healthy
test -z "$(docker compose port db 5432 2>/dev/null || true)"

app_psql() {
    docker compose exec -T db sh -ec '
        export PGPASSWORD="$DB_APP_PASSWORD"
        exec psql -w -h 127.0.0.1 -U enot_app -d enot -v ON_ERROR_STOP=1 "$@"
    ' sh "$@"
}

test "$(app_psql -Atqc 'SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = current_user')" = f
app_psql -c 'CREATE TABLE public.devops_smoke (id integer PRIMARY KEY); INSERT INTO public.devops_smoke VALUES (42);'
docker compose down
docker compose up -d --wait --wait-timeout 120 db
test "$(app_psql -Atqc 'SELECT id FROM public.devops_smoke')" = 42

docker compose exec -T db createdb -U postgres -O enot_app enot_restore_check
docker compose exec -T db pg_dump -U postgres -d enot -Fc |
    docker compose exec -T db pg_restore -U postgres -d enot_restore_check --single-transaction --no-owner --no-privileges --role=enot_app
test "$(docker compose exec -T db psql -U postgres -d enot_restore_check -Atqc 'SELECT id FROM public.devops_smoke')" = 42
echo 'PostgreSQL readiness, access restrictions, volume persistence, and restore verified.'
