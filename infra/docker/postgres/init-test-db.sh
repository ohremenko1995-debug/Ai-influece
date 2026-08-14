#!/bin/sh
# Runs once, during the first initialisation of the Postgres data directory.
# Creates the dedicated test database so `make test-api` never touches dev data.
set -eu

TEST_DB="${POSTGRES_TEST_DB:-influenceros_test}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set ON_ERROR_STOP=1 <<-EOSQL
	SELECT 'CREATE DATABASE "${TEST_DB}" OWNER "${POSTGRES_USER}"'
	WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${TEST_DB}')\gexec
EOSQL

echo "init-test-db: ensured database ${TEST_DB}"
