-- Enable pgvector extension for vector similarity search.
-- Runs on first database creation via Docker entrypoint.
CREATE EXTENSION IF NOT EXISTS vector;
