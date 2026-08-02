"""PostgreSQL store for matters, hearings and documents.

Deliberately separate from :mod:`storage_service`, which backs OAuth and is
only initialised when ``ENABLE_AUTH`` is true. Matters and documents must work
in local development with auth switched off, so this store owns its own pool
and its own schema, driven by the same ``POSTGRES_*`` settings.

The schema is created idempotently on first connect. pgvector is optional: if
the extension is unavailable the embedding column is skipped and document
search falls back to Postgres full-text, which is reported rather than silently
substituted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncpg

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS matters (
        id                  BIGSERIAL PRIMARY KEY,
        reference           TEXT UNIQUE,
        title               TEXT NOT NULL,
        matter_type         TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'open',
        court               TEXT,
        case_number         TEXT,
        cnr                 TEXT,
        parties             JSONB NOT NULL DEFAULT '[]'::jsonb,
        cause_of_action_date DATE,
        filing_date         DATE,
        limitation_expiry   DATE,
        claim_value         NUMERIC,
        opposing_counsel    TEXT,
        notes               TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_matters_status ON matters (status)",
    "CREATE INDEX IF NOT EXISTS idx_matters_type ON matters (matter_type)",
    """
    CREATE TABLE IF NOT EXISTS hearings (
        id            BIGSERIAL PRIMARY KEY,
        matter_id     BIGINT NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
        hearing_date  DATE NOT NULL,
        purpose       TEXT,
        bench         TEXT,
        outcome       TEXT,
        next_date     DATE,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_hearings_matter ON hearings (matter_id)",
    "CREATE INDEX IF NOT EXISTS idx_hearings_date ON hearings (hearing_date)",
    """
    CREATE TABLE IF NOT EXISTS matter_events (
        id          BIGSERIAL PRIMARY KEY,
        matter_id   BIGINT NOT NULL REFERENCES matters(id) ON DELETE CASCADE,
        event_date  DATE NOT NULL,
        event_type  TEXT NOT NULL,
        description TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_matter ON matter_events (matter_id)",
    """
    CREATE TABLE IF NOT EXISTS documents (
        id            BIGSERIAL PRIMARY KEY,
        matter_id     BIGINT REFERENCES matters(id) ON DELETE SET NULL,
        title         TEXT NOT NULL,
        doc_type      TEXT,
        source_path   TEXT,
        sha256        TEXT UNIQUE,
        page_count    INTEGER,
        char_count    INTEGER,
        full_text     TEXT,
        metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_documents_matter ON documents (matter_id)",
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
        id            BIGSERIAL PRIMARY KEY,
        document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        chunk_index   INTEGER NOT NULL,
        heading_path  TEXT,
        content       TEXT NOT NULL,
        tsv           TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
        UNIQUE (document_id, chunk_index)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON document_chunks USING GIN (tsv)",
    "CREATE INDEX IF NOT EXISTS idx_chunks_document ON document_chunks (document_id)",
    """
    CREATE TABLE IF NOT EXISTS saved_research (
        id            BIGSERIAL PRIMARY KEY,
        matter_id     BIGINT REFERENCES matters(id) ON DELETE SET NULL,
        issue         TEXT NOT NULL,
        payload       JSONB NOT NULL,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]


class LegalStore:
    """Connection pool and schema owner for legal matter and document data."""

    def __init__(self) -> None:
        """Create an unconnected store."""
        self.pool: Optional[asyncpg.Pool] = None
        self.vector_enabled = False
        self._connect_error: Optional[str] = None

    @property
    def connected(self) -> bool:
        """Whether the pool is live."""
        return self.pool is not None

    @property
    def last_error(self) -> Optional[str]:
        """The most recent connection failure, for reporting in tool output."""
        return self._connect_error

    def _dsn(self) -> str:
        return (
            f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}"
            f"/{settings.POSTGRES_DB}"
        )

    async def connect(self) -> None:
        """Open the pool and create the schema.

        Raises:
            ConnectionError: If Postgres is unreachable or misconfigured.
        """
        if self.pool is not None:
            return

        missing = [
            name
            for name in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER")
            if not getattr(settings, name)
        ]
        if missing:
            self._connect_error = (
                f"PostgreSQL is not configured: {', '.join(missing)} unset."
            )
            raise ConnectionError(self._connect_error)

        try:
            self.pool = await asyncpg.create_pool(
                self._dsn(),
                min_size=1,
                max_size=settings.POSTGRES_MAX_CONNECTIONS,
                command_timeout=30,
            )
        except Exception as e:
            self._connect_error = str(e)
            logger.error(f"Legal store could not connect to PostgreSQL: {e}")
            raise ConnectionError(f"PostgreSQL connection failed: {e}") from e

        await self._migrate()
        self._connect_error = None
        logger.info("Legal store connected and schema ensured")

    async def _migrate(self) -> None:
        """Create tables and, where available, the pgvector column."""
        assert self.pool is not None

        async with self.pool.acquire() as conn:
            for statement in SCHEMA_STATEMENTS:
                await conn.execute(statement)

            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                await conn.execute(
                    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS "
                    f"embedding vector({settings.EMBEDDING_DIMENSIONS})"
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
                    "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
                )
                self.vector_enabled = True
                logger.info(
                    "pgvector enabled with "
                    f"{settings.EMBEDDING_DIMENSIONS}-dimensional embeddings"
                )
            except Exception as e:
                self.vector_enabled = False
                logger.warning(
                    f"pgvector unavailable ({e}). Document search will use "
                    "Postgres full-text only. Use the pgvector/pgvector image to "
                    "enable semantic search."
                )

    async def disconnect(self) -> None:
        """Close the pool."""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            logger.info("Legal store disconnected")

    async def health(self) -> Dict[str, Any]:
        """Report store availability for tool output."""
        if self.pool is None:
            return {
                "connected": False,
                "vector_enabled": False,
                "error": self._connect_error,
            }
        try:
            async with self.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"connected": True, "vector_enabled": self.vector_enabled}
        except Exception as e:
            return {"connected": False, "vector_enabled": False, "error": str(e)}

    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        """Run a query returning rows."""
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        """Run a query returning at most one row."""
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Run a query returning a single value."""
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Run a statement returning no rows."""
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            await self.connect()
        assert self.pool is not None
        return self.pool


_store: Optional[LegalStore] = None


def get_store() -> LegalStore:
    """Return the process-wide legal store."""
    global _store
    if _store is None:
        _store = LegalStore()
    return _store


async def close_store() -> None:
    """Close and drop the process-wide store."""
    global _store
    if _store is not None:
        await _store.disconnect()
        _store = None


STORAGE_UNAVAILABLE_MESSAGE = (
    "The matter and document database is not reachable, so nothing was read or "
    "written. Start PostgreSQL (podman compose up postgres) and check the "
    "POSTGRES_* settings. Do not proceed as though the record was saved."
)


def unavailable_response(operation: str, error: Exception) -> Dict[str, Any]:
    """Standard response when the store cannot be reached."""
    return {
        "status": "unavailable",
        "operation": operation,
        "error": str(error),
        "message": STORAGE_UNAVAILABLE_MESSAGE,
    }
