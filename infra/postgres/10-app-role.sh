#!/usr/bin/env bash
# Sourced by the official PostgreSQL entrypoint on an empty data volume.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password DB_APP_PASSWORD
\getenv app_database POSTGRES_DB
CREATE ROLE enot_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
REVOKE CONNECT, TEMPORARY ON DATABASE :"app_database" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"app_database" TO enot_app;
GRANT USAGE, CREATE ON SCHEMA public TO enot_app;
SQL
