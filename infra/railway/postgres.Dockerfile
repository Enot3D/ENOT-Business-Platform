FROM postgres:16-bookworm
COPY --chmod=0644 infra/postgres/10-app-role.sh /docker-entrypoint-initdb.d/10-app-role.sh
