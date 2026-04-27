-- Extensions and shared setup (runs first on all DBs)
\c tank
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";
