-- One PostgreSQL server locally, one database per service (database-per-service pattern).
-- In Azure each service gets its own database on Azure Database for PostgreSQL Flexible Server.
CREATE DATABASE identity;
CREATE DATABASE listing;
CREATE DATABASE search;
CREATE DATABASE ai;

\c search
CREATE EXTENSION IF NOT EXISTS vector;

\c ai
CREATE EXTENSION IF NOT EXISTS vector;
