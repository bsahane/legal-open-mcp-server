# Performance Optimization for legal-mcp Server

> **Decision**: Which optimizations to apply — and in what order — to reduce document search latency, case-law query response times, and citation verification throughput in the legal-mcp Python MCP server.

> **Type**: Technical
> **Status**: Complete
> **Date**: 2026-08-20

> **ARCHIVED (2026-08-22):** this study's recommendations have been implemented
> (DuckDB FTS index, persistent read-only connections with thread-local reuse,
> long-lived httpx clients, bounded-concurrency citation sweeps, disk cache).
> Kept for design rationale; see `PERFORMANCE_OPTIMIZATION_PLAN.md` and
> `CHANGELOG.md` for what shipped.

---

## Executive Summary

The legal-mcp server has **six high-impact performance bottlenecks**, all addressable without architectural rewrites. The evidence strongly recommends prioritising in this order:

1. **DuckDB connection reuse** — the single largest win. The current code creates and destroys a DuckDB connection on every query ([`_connect()` → `duckdb.connect()`](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py#L552-L561), closed in `finally`). This discards DuckDB's metadata cache and Parquet statistics on every call. A persistent read-only connection eliminates repeated initialisation and lets DuckDB cache row-group metadata across queries.

2. **httpx client lifecycle** — the Indian Kanoon client creates a new `httpx.AsyncClient` per `_post()` call (inside the lock, line 274), and the sync/PDF-download paths do the same. Each new client forces a full TCP+TLS handshake. A long-lived, process-scoped client with tuned pool limits reuses connections.

3. **DuckDB FTS extension** — the current search uses `lower(title) LIKE ?` with `%term%` patterns, which forces a sequential scan of every row on every query. DuckDB's built-in FTS extension with BM25 ranking would provide O(log N) lookup with relevance scoring.

4. **Semaphore-based concurrency control** for citation verification — the current `asyncio.gather` batching in chunks of 8 is correct but suboptimal: it blocks until the slowest citation in each batch completes before starting the next batch. A semaphore wrapping all tasks at once keeps the concurrency pipe full.

5. **Cache upgrade** from raw JSON files to `diskcache` — the current cache writes individual JSON files with `json.dump`/`json.load`, which risks corruption under concurrent writes and has no eviction policy. `diskcache` provides ACID transactions, LRU eviction, and SQLite-backed persistence.

6. **Embedding and template optimizations** — fastembed batching, Jinja2 bytecode caching, and pgvector HNSW tuning provide incremental but real gains.

The biggest caveat: **DuckDB's FTS extension requires an index-building step** that must be integrated into the `make corpus` workflow. Without it, the LIKE-based search remains the fallback.

---

## 1. DuckDB Query Optimization

### 1.1 Persistent Connection (Critical)

**Current state**: Every search, metadata lookup, citation lookup, and court-discovery call in [`open_judgments.py`](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py) calls `self._connect()` which creates a fresh `duckdb.connect()`, then closes it in a `finally` block.

**Problem**: DuckDB caches Parquet file metadata (schemas, row-group statistics, min/max values) in memory within a connection. Closing the connection discards this cache. For the Hive-partitioned corpus (SC metadata at `year=*/metadata.parquet`, HC at `year=*/court=*/bench=*/metadata.parquet`), this means re-reading Parquet footers on every query. [DuckDB documentation, duckdb.org, accessed 2026-08-20]

**Recommendation**: Replace `_connect()` with a lazily-initialised, process-scoped, read-only DuckDB connection held on the `OpenJudgmentsClient` instance. DuckDB supports concurrent read-only queries on a single in-memory connection, which maps to the server's read-only workload. [DuckDB concurrency docs, duckdb.org, accessed 2026-08-20]

```python
# On OpenJudgmentsClient
_duckdb_conn: Optional["duckdb.DuckDBPyConnection"] = None

def _connect(self):
    if self._duckdb_conn is None:
        import duckdb
        self._duckdb_conn = duckdb.connect()  # in-memory, read-only workload
    return self._duckdb_conn
```

Remove the `con.close()` calls from `_run()` lambdas; instead, close in an `atexit` handler or a `shutdown()` method.

**Impact**: Eliminates repeated Parquet metadata parsing. On a corpus with ~30 year-partitioned SC files and hundreds of HC bench files, this alone can reduce query latency from seconds to sub-100ms for warm queries. [Medium: DuckDB Parquet optimization, 2024; DuckDB docs: predicate pushdown, 2025]

### 1.2 Full-Text Search Extension (High)

**Current state**: Search in [`open_judgments.py` lines 800–808](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py#L800-L808) splits the query into terms and builds `lower(title) LIKE ? OR lower(description) LIKE ?` for each term, which forces a full sequential scan.

**Problem**: `LIKE '%term%'` cannot use any index or statistics; DuckDB must decompress and scan every string in every row group. This is O(N) per term per column. [DuckDB docs: pattern matching performance, accessed 2026-08-20]

**Recommendation**: Use DuckDB's built-in `fts` extension:

1. During `make corpus` (or `sync`), after downloading Parquet, load the data into a persistent DuckDB file and create an FTS index:
   ```sql
   INSTALL fts; LOAD fts;
   CREATE TABLE corpus AS SELECT * FROM read_parquet('...');
   PRAGMA create_fts_index('corpus', 'doc_id', 'title', 'description', 'judge');
   ```
2. At query time, use `match_bm25` for ranked retrieval:
   ```sql
   SELECT *, fts_main_corpus.match_bm25(rowid, ?) AS score
   FROM corpus
   WHERE score IS NOT NULL
   ORDER BY score DESC
   LIMIT ?
   ```

This provides tokenization, stemming, and BM25 relevance ranking, bringing search latency from O(N) sequential scan to O(log N) index lookup. [DuckDB FTS extension docs, duckdb.org, 2025]

**Tradeoff**: Requires a build step and a persistent `.duckdb` file (~2× the Parquet size). The current LIKE-based search should be kept as a fallback for when FTS is not built.

### 1.3 Partition Pruning and Column Projection (Medium)

**Current state**: The UNION ALL query in `_search_sql` already uses `hive_partitioning = true`, which is correct. However:

- The query `SELECT *` from each Parquet source reads all columns, including ones never used in search results (e.g., `path`, `pdf_link`).
- The `WHERE court = ?` filter on HC data is applied *after* the UNION, not pushed down into the `read_parquet` call.

**Recommendations**:
- **Explicit column projection**: Replace `SELECT *` with only the columns needed. DuckDB pushes column projection into the Parquet reader, skipping decompression of unused columns. [DuckDB docs: projection pushdown, accessed 2026-08-20]
- **Sort the Parquet data** by `decision_date` (the ORDER BY column) before writing. This makes DuckDB's zone-map statistics effective for the `decision_date >= ? AND decision_date <= ?` filters, allowing row-group skipping. [Medium: DuckDB Parquet optimization, 2024]
- **Merge small files**: If individual year-court-bench Parquet files are under 1 MB, merge them into larger files (~100 MB+) to reduce metadata overhead. [MotherDuck blog: small file problem, 2025]

### 1.4 Citation Lookup Optimization (Medium)

**Current state**: [`find_by_citation`](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py#L860-L931) uses `regexp_replace(lower(...))` on every row for citation normalisation, which is expensive.

**Recommendation**: Pre-compute the normalised citation as a column during corpus build, then use a simple equality match. This turns an O(N) regex scan into a constant-time lookup if the column is sorted or indexed.

---

## 2. Connection Pooling Patterns

### 2.1 httpx Client Reuse (Critical)

**Current state**: The Indian Kanoon client creates a new `httpx.AsyncClient` inside `_post()` at [line 274](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/indian_kanoon.py#L274-L278):

```python
async with httpx.AsyncClient(
    base_url=self._base_url,
    timeout=REQUEST_TIMEOUT_SECONDS,
    transport=self._transport,
) as client:
```

The sync client in `open_judgments.py` does the same for S3 downloads at [line 429](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py#L429) and PDF fetches at [line 1009](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/open_judgments.py#L1009-L1011).

**Problem**: Every `async with httpx.AsyncClient()` creates a new connection pool, performs TCP + TLS handshake, and tears it down. For the Indian Kanoon API (HTTPS to `api.indiankanoon.org`), each handshake adds ~100-300ms of latency. For batched citation verification (8 concurrent), this multiplies across every batch. [httpx docs: connection pooling, python-httpx.org, accessed 2026-08-20]

**Recommendation**: Create a long-lived `httpx.AsyncClient` on `IndianKanoonClient.__init__` and close it via an explicit `close()` method or `atexit`:

```python
class IndianKanoonClient:
    def __init__(self, ...):
        ...
        limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
            limits=limits,
            http2=True,  # Multiplexing if API supports it
        )

    async def close(self):
        await self._client.aclose()
```

Similarly for `OpenJudgmentsClient`, create a shared client for S3/PDF fetches.

**Impact**: Eliminates per-request TLS handshake overhead. For citation verification of 20 citations, this alone can save 2-6 seconds of cumulative handshake time. [httpx docs: performance best practices, python-httpx.org, 2025]

### 2.2 asyncpg Connection Pool (Medium)

If pgvector/Postgres is used for embedding search, use `asyncpg.create_pool()` at application startup:

```python
pool = await asyncpg.create_pool(
    dsn=settings.DATABASE_URL,
    min_size=2,
    max_size=10,
    command_timeout=30.0,
)
```

Use `SET LOCAL hnsw.ef_search = 100` within transactions to tune search quality per-query without polluting the pool. [pgvector docs, PostgreSQL; asyncpg pool docs, accessed 2026-08-20]

---

## 3. Async I/O Best Practices

### 3.1 Semaphore-Based Concurrency (High)

**Current state**: Citation verification in [`research_tools.py` lines 766-771](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/tools/research_tools.py#L766-L771) uses chunked `asyncio.gather`:

```python
for i in range(0, len(found), _CONCURRENCY):
    batch = found[i : i + _CONCURRENCY]
    results = await asyncio.gather(
        *[_check_one(c, budget_ref) for c in batch]
    )
```

**Problem**: This waits for the slowest citation in each batch of 8 before starting the next batch. If 7 citations resolve in 50ms but one takes 2 seconds, the remaining citations wait. [Python asyncio docs; multiple async best-practice guides, 2025]

**Recommendation**: Use `asyncio.Semaphore` to create all tasks at once, bounded by concurrency:

```python
semaphore = asyncio.Semaphore(_CONCURRENCY)

async def _bounded_check(citation, budget_ref):
    async with semaphore:
        return await _check_one(citation, budget_ref)

results = await asyncio.gather(
    *[_bounded_check(c, budget_ref) for c in found]
)
```

This keeps 8 citations in-flight at all times, with new ones starting as soon as any one finishes. For Python 3.11+, consider `asyncio.TaskGroup` for better error propagation. [Python asyncio docs; Medium: async concurrency patterns, 2024]

**Impact**: For 20 citations with variable latency, this can reduce total verification time by 30-50% compared to fixed-batch processing.

### 3.2 `asyncio.to_thread` for DuckDB (Already Correct)

The current code correctly wraps synchronous DuckDB calls in `asyncio.to_thread(_run)`, preventing event-loop blocking. This is the right pattern. [Python 3.9+ asyncio docs]

### 3.3 Event Loop Optimization (Low Priority)

For production deployment, consider replacing the default asyncio event loop with `uvloop`:

```python
# In main.py or startup
import uvloop
uvloop.install()
```

Typical gains: 2-4× throughput improvement for I/O-bound workloads. [uvloop benchmarks, MagicStack, 2024]

---

## 4. Embedding Search Acceleration

### 4.1 fastembed Batching (Medium)

**Current state**: The [`LocalProvider`](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/sources/embeddings.py#L87-L118) calls `self._model.embed(texts)` and `self._model.embed([text])` which use default batch sizes.

**Recommendations**:
- For `embed_documents`: Enable parallel processing with `parallel=0` (auto-detect cores) for large batches:
  ```python
  list(self._model.embed(texts, batch_size=256, parallel=0))
  ```
- For `embed_query`: Single queries cannot be batched, but ensure the model stays loaded (current singleton pattern is correct).
- Consider `lazy_load=True` when using parallel workers to reduce memory overhead. [fastembed docs, Qdrant, 2025]

### 4.2 pgvector HNSW Tuning (Medium)

If using pgvector for semantic search:

- **Use HNSW over IVFFlat**: HNSW provides higher recall with lower latency for read-heavy workloads.
- **Index parameters**: `m=16`, `ef_construction=128` (higher than default 64 for better quality).
- **Query-time tuning**: `SET LOCAL hnsw.ef_search = 100` (default is 40; 100 gives ~99% recall).
- **Use `halfvec`**: If your embedding model produces 1024-dim vectors, `halfvec` halves memory usage with <1% recall loss. Available in pgvector 0.7.0+. [pgvector tuning guide, PostgreSQL wiki; BigData Boutique benchmark, 2024]

### 4.3 Embedding Cache (Medium)

Cache query embeddings for repeated identical queries (common in citation verification where the same citation text maps to the same embedding):

```python
_query_embedding_cache: Dict[str, List[float]] = {}

async def embed_query(self, text: str) -> List[float]:
    if text in self._query_embedding_cache:
        return self._query_embedding_cache[text]
    result = list(map(float, next(iter(self._model.embed([text])))))
    self._query_embedding_cache[text] = result
    return result
```

---

## 5. Caching Architecture

### 5.1 Upgrade to diskcache (High)

**Current state**: The [cache module](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/cache.py) writes individual JSON files with `json.dump`/`json.load`, with a 24h TTL enforced by checking timestamps.

**Problems**:
- **No atomicity**: Concurrent writes to the same key can produce corrupt JSON.
- **No eviction**: Old entries accumulate indefinitely (only TTL-based removal on read).
- **Performance**: Individual file I/O per cache operation.
- **Blocking I/O**: `json.load`/`json.dump` are synchronous and called from async context via tools.

**Recommendation**: Replace with `diskcache.Cache`:

```python
import diskcache
from functools import lru_cache

@lru_cache(maxsize=1)
def _get_cache() -> diskcache.Cache:
    return diskcache.Cache(
        str(Path(settings.LEGAL_DATA_PATH) / "cache" / "case_law"),
        size_limit=500 * 1024 * 1024,  # 500 MB
    )

async def get_cached(...) -> Optional[Any]:
    cache = _get_cache()
    key = _cache_key(query, court, from_date, to_date, judge, limit, page)
    return await asyncio.to_thread(cache.get, key)

async def set_cached(data, ...) -> None:
    cache = _get_cache()
    key = _cache_key(...)
    await asyncio.to_thread(cache.set, key, data, expire=CACHE_TTL_SECONDS)
```

`diskcache` provides ACID transactions (SQLite-backed), automatic LRU eviction, and is safe for concurrent access. The `asyncio.to_thread` wrapper keeps the event loop non-blocking. [diskcache docs, Grant Jenks; Cache library comparison, 2025]

### 5.2 In-Memory LRU for Hot Paths (Medium)

Add an in-process LRU cache in front of disk cache for the hottest paths (e.g., court resolution, statute abbreviation expansion):

```python
from functools import lru_cache

@lru_cache(maxsize=256)
def resolve_court(court: Optional[str]) -> Optional[str]:
    ...  # existing logic
```

The `resolve_court` function is already pure and deterministic — perfect for `lru_cache`.

---

## 6. Streaming and Progressive Response Patterns

### 6.1 FastMCP Progress Reporting (High)

**Current state**: Long-running tools like `verify_all_citations` and `build_research_memo` return only after all work is complete.

**Recommendation**: Use FastMCP's built-in `ctx.report_progress()` to provide real-time updates:

```python
async def verify_all_citations(text: str, ..., ctx: Context) -> Dict[str, Any]:
    found = cit.extract_all(text)
    total = len(found)

    for i, citation in enumerate(found):
        await ctx.report_progress(i, total)
        ...
```

This lets the calling AI client show progress (e.g., "Verifying citation 12/20") instead of appearing frozen. [FastMCP docs: progress reporting, gofastmcp.com, 2025]

### 6.2 Streamable HTTP Transport (Medium)

**Current state**: The server supports `http`, `sse`, and `streamable-http` transports (configured via `MCP_TRANSPORT_PROTOCOL`).

**Recommendation**: Default to `streamable-http` for production deployments. It uses a single endpoint for requests and streaming responses, reducing connection overhead compared to the dual-channel SSE approach. [MCP specification: streamable HTTP transport, modelcontextprotocol.io, 2025]

---

## 7. Jinja2 Template Optimization

### 7.1 Bytecode Caching (Medium)

**Current state**: Templates are loaded from the [`templates/`](file:///Users/bsahane/Developer/claude/legal-mcp/legal_mcp_server/src/templates) directory. If the `Environment` is not configured with a bytecode cache, templates are re-parsed on every render.

**Recommendation**: Configure `FileSystemBytecodeCache`:

```python
from jinja2 import Environment, FileSystemLoader, FileSystemBytecodeCache

env = Environment(
    loader=FileSystemLoader("templates/"),
    bytecode_cache=FileSystemBytecodeCache(
        directory=str(Path(settings.LEGAL_DATA_PATH) / "cache" / "jinja2")
    ),
    auto_reload=False,  # In production
)
```

`auto_reload=False` prevents stat calls on every render. [Jinja2 docs: bytecode caching, palletsprojects.com, 2025]

### 7.2 Shared Environment (Low)

Ensure the Jinja2 `Environment` is instantiated once at module level, not per-request. Creating a new `Environment` per render is a common performance anti-pattern. [Jinja2 docs: API, palletsprojects.com]

---

## Cross-Dimension Insights

Three insights emerge only from the combination of dimensions:

1. **The DuckDB connection fix and httpx client reuse are multiplicative with the semaphore-based concurrency**. Currently, each citation verification opens a new DuckDB connection AND a new httpx client. If you fix connections but leave the batched gather, you get 8× the benefit per batch. If you fix concurrency but leave per-query connections, each of the 8 concurrent tasks still pays the connection overhead. Fixing all three transforms the citation verification pipeline from sequential-connection-per-query to pipelined-reuse.

2. **The FTS extension and the diskcache upgrade serve the same user-facing goal** (fast search) but at different cache layers. FTS makes the first (cold) search fast; diskcache makes repeated searches instant. Implementing both gives the ideal latency profile: first query in ~50ms (FTS), repeated queries in ~1ms (cache).

3. **Progressive response patterns become more valuable as the underlying operations get faster**. When each citation takes 2 seconds (due to connection overhead), progress reporting just shows a slow crawl. When each citation takes 50ms (with connection reuse), progress reporting shows a satisfying rapid-fire update. The UX improvement is non-linear: fast + visible > fast + invisible > slow + visible.

---

## Recommendations

### Priority 1 — Immediate (hours of work, largest impact)

| # | Change | Impact | Effort | Confidence |
|---|--------|--------|--------|------------|
| 1 | Persistent DuckDB connection on `OpenJudgmentsClient` | 5-50× faster warm queries | Low | **High** — well-documented DuckDB behaviour [1][2] |
| 2 | Long-lived `httpx.AsyncClient` on `IndianKanoonClient` | ~100-300ms saved per API call | Low | **High** — httpx docs explicitly recommend this [3][4] |
| 3 | Semaphore-based concurrency for citation verification | 30-50% faster batch verification | Low | **High** — standard asyncio pattern [5] |

### Priority 2 — Short-term (days of work, significant impact)

| # | Change | Impact | Effort | Confidence |
|---|--------|--------|--------|------------|
| 4 | Replace JSON file cache with `diskcache` | Eliminates corruption risk, automatic eviction, faster I/O | Medium | **High** — diskcache is battle-tested [6] |
| 5 | DuckDB FTS extension for corpus search | O(N) → O(log N) search, relevance ranking | Medium | **High** — FTS extension is production-quality [7] |
| 6 | FastMCP `ctx.report_progress()` for long tools | Better UX, no architectural change needed | Low | **High** — native FastMCP feature [8] |

### Priority 3 — Medium-term (iterative improvement)

| # | Change | Impact | Effort | Confidence |
|---|--------|--------|--------|------------|
| 7 | Explicit column projection in DuckDB queries | Reduced I/O and decompression | Low | **Medium** — depends on column count [9] |
| 8 | Pre-computed normalised citation column | Faster citation lookups | Medium | **High** — eliminates per-query regex [10] |
| 9 | Jinja2 bytecode cache + shared Environment | Faster template rendering | Low | **Medium** — marginal unless templates are large [11] |
| 10 | pgvector HNSW tuning (ef_search, halfvec) | Higher recall at lower latency | Low | **Medium** — depends on vector count [12] |
| 11 | fastembed parallel processing for bulk embeds | Faster document ingestion | Low | **Medium** — only matters for batch operations [13] |
| 12 | uvloop for event loop | 2-4× throughput improvement | Low | **Medium** — platform-dependent [14] |

---

## Open Questions

1. **Corpus size**: How many total rows are in the combined SC + HC Parquet corpus? This determines whether FTS is necessary (>100K rows: yes) or whether the persistent connection alone makes LIKE fast enough (<10K rows: maybe).

2. **pgvector adoption status**: Is pgvector/asyncpg currently deployed in production, or is it planned? The embedding search acceleration recommendations depend on this.

3. **Concurrent sessions**: How many concurrent MCP sessions does the server typically handle? This affects whether a single DuckDB connection suffices or whether a connection pool is needed.

4. **Cache hit rate**: What fraction of case-law searches are repeated queries within the 24h TTL? If >50%, the cache upgrade should be Priority 1; if <10%, Priority 3.

---

## Source Appendix

| # | Claim | Publisher | Pub Date | Accessed | Confidence |
|---|-------|-----------|----------|----------|------------|
| [1] | DuckDB caches Parquet metadata within a connection | DuckDB documentation, duckdb.org | 2025 | 2026-08-20 | High |
| [2] | Persistent connections eliminate repeated metadata parsing | DuckDB documentation, duckdb.org | 2025 | 2026-08-20 | High |
| [3] | httpx recommends reusing AsyncClient instances | httpx documentation, python-httpx.org | 2025 | 2026-08-20 | High |
| [4] | Each new AsyncClient forces TCP+TLS handshake | httpx connection pooling docs, python-httpx.org | 2025 | 2026-08-20 | High |
| [5] | Semaphore + gather keeps concurrency pipe full | Python asyncio documentation; Multiple async guides | 2024-2025 | 2026-08-20 | High |
| [6] | diskcache provides ACID transactions via SQLite | diskcache documentation, Grant Jenks | 2024 | 2026-08-20 | High |
| [7] | DuckDB FTS provides O(log N) lookup with BM25 | DuckDB FTS extension documentation, duckdb.org | 2025 | 2026-08-20 | High |
| [8] | FastMCP ctx.report_progress for real-time updates | FastMCP documentation, gofastmcp.com | 2025 | 2026-08-20 | High |
| [9] | Column projection pushdown reduces Parquet I/O | DuckDB documentation, duckdb.org | 2025 | 2026-08-20 | High |
| [10] | Regex per-row operations are O(N) without indexes | DuckDB pattern matching docs, duckdb.org | 2025 | 2026-08-20 | High |
| [11] | Jinja2 FileSystemBytecodeCache prevents re-parsing | Jinja2 documentation, palletsprojects.com | 2025 | 2026-08-20 | Medium |
| [12] | HNSW ef_search=100 gives ~99% recall | pgvector tuning guide; BigData Boutique benchmark | 2024 | 2026-08-20 | Medium |
| [13] | fastembed parallel=0 uses all CPU cores | fastembed documentation, Qdrant | 2025 | 2026-08-20 | Medium |
| [14] | uvloop provides 2-4× throughput improvement | uvloop benchmarks, MagicStack | 2024 | 2026-08-20 | Medium |

---

## Staleness Map

| Claim Class | Freshness Window | Earliest Re-check |
|-------------|------------------|--------------------|
| DuckDB version/API compatibility | 1 month | 2026-09-20 |
| httpx connection pooling API | 3 months | 2026-11-20 |
| FastMCP progress reporting API | 3 months | 2026-11-20 |
| pgvector HNSW parameters | 6 months | 2027-02-20 |
| fastembed batch/parallel API | 6 months | 2027-02-20 |
| General async patterns | 12 months | 2027-08-20 |
