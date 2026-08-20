# Performance Optimization Plan — Legal MCP Server

## Optimization 1: `asyncio.gather` Concurrency Patch (PRIMARY)

**Problem:** `verify_all_citations` (in `legal_mcp_server/src/tools/research_tools.py`, lines 680-733) processes citations one-at-a-time in a `for` loop. Each iteration calls `_verify_case_citation_dual` which makes an HTTP request — meaning only 1 network call happens at a time. With 10 case citations, this is 10 sequential round-trips.

**Fix:** Batch citations into groups of 8 and process each batch concurrently with `asyncio.gather`. The slow HTTP calls happen in parallel instead of sequentially.

### Changes needed:

#### A. Add `import asyncio`
Insert `import asyncio` after the last `from .` import line (around line 19, after `from legal_mcp_server.src.sources.case_law import SourceUnavailable`).

#### B. Replace lines 680-733 with this block:

```python
 case_budget = max(0, max_citations)
 _CONCURRENCY = 8

 async def _check_one(
 citation: cit.Citation, budget_ref: list
 ) -> Dict[str, Any]:
 if citation.kind is cit.CitationKind.CASE:
 if budget_ref[0] <= 0:
 return {
 "citation": citation.raw,
 "parsed": citation.to_dict(),
 "verdict": VERDICT_UNCHECKED,
 "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
 "matches": [],
 "note": (
 "Skipped: max_citations limit reached. "
 "This citation was NOT checked."
 ),
 }
 budget_ref[0] -= 1
 try:
 outcome = await _verify_case_citation_dual(
 citation,
 use_fallback=use_dual_source,
 max_fallback_budget=budget_ref[0],
 )
 except SourceUnavailable as e:
 return {
 "citation": citation.raw,
 "parsed": citation.to_dict(),
 "verdict": VERDICT_UNCHECKED,
 "confidence": CONFIDENCE_SCORES[VERDICT_UNCHECKED],
 "matches": [],
 "note": f"Source unavailable, not checked: {e}",
 }
 return {
 "citation": citation.raw,
 "parsed": citation.to_dict(),
 "verdict": outcome["verdict"],
 "confidence": outcome.get(
 "confidence",
 CONFIDENCE_SCORES.get(outcome["verdict"], 0.0),
 ),
 "matches": outcome.get("matches", []),
 "note": outcome.get("note", ""),
 }
 outcome = _verify_statutory_citation(citation)
 return {
 "citation": citation.raw,
 "parsed": citation.to_dict(),
 "verdict": outcome["verdict"],
 "confidence": outcome.get(
 "confidence",
 CONFIDENCE_SCORES.get(outcome["verdict"], 0.0),
 ),
 "matches": outcome.get("matches", []),
 "note": outcome.get("note", ""),
 }

 budget_ref = [case_budget]
 checked: List[Dict[str, Any]] = []
 for i in range(0, len(found), _CONCURRENCY):
 batch = found[i : i + _CONCURRENCY]
 results = await asyncio.gather(
 *[_check_one(c, budget_ref) for c in batch]
 )
 checked.extend(results)

 skipped = sum(
 1 for c in checked if "Skipped" in c.get("note", "")
 )

 verification_summary = _build_verification_summary(checked)
```

**Key design decisions:**
- `_CONCURRENCY = 8` — processes 8 citations per batch. Enough to saturate the network without overwhelming the remote source.
- `budget_ref = [case_budget]` — mutable list so the shared budget counter is visible across all coroutines. Avoids race conditions on the `case_budget` counter.
- `skipped` is computed post-hoc from the `checked` list rather than tracked during execution (simpler, no race conditions).
- Statutory citations (non-case) run synchronously inside each coroutine — they're fast enough that concurrency isn't needed.

**Expected speedup:** ~8x for typical sweeps with mixed case + statutory citations.

---

## Optimization 2: Redis/disk Caching for Case Law Queries (SECONDARY)

**Problem:** `search_case_law` hits the remote corpus every time. The same query (e.g., "cheque dishonour section 138") is fetched repeatedly across sessions.

**Approach:** Add a file-system based cache (avoiding the operational overhead of Redis) for case law search results.

### Recommended design:

```
data/cache/
└── case_law/
 ├── <query_hash>.json # search results cached by query+params
 └── _index.json # TTL tracking, cache hit stats
```

### Changes needed:

#### A. Create `legal_mcp_server/src/cache.py`

```python
import hashlib
import json
import time
import os
from pathlib import Path

CACHE_DIR = Path("data/cache/case_law")
CACHE_TTL_SECONDS = 86400 # 24 hours
INDEX_FILE = CACHE_DIR / "_index.json"

def _make_key(query, court, from_date, to_date, judge, limit, page):
 raw = f"{query}|{court}|{from_date}|{to_date}|{judge}|{limit}|{page}"
 return hashlib.sha256(raw.encode()).hexdigest()[:16]

def get_cached(query, court, from_date, to_date, judge, limit, page):
 key = _make_key(query, court, from_date, to_date, judge, limit, page)
 path = CACHE_DIR / f"{key}.json"
 if not path.exists():
 return None
 with open(path) as f:
 entry = json.load(f)
 if time.time() - entry["ts"] > CACHE_TTL_SECONDS:
 path.unlink(missing_ok=True)
 return None
 return entry["data"]

def set_cached(data, query, court, from_date, to_date, judge, limit, page):
 CACHE_DIR.mkdir(parents=True, exist_ok=True)
 key = _make_key(query, court, from_date, to_date, judge, limit, page)
 path = CACHE_DIR / f"{key}.json"
 with open(path, "w") as f:
 json.dump({"ts": time.time(), "data": data}, f)
```

#### B. Modify `search_case_law` in `research_tools.py`

Wrap the function body with cache lookup/store:

```python
# At top of function body, before the search
cached = get_cached(query, court, from_date, to_date, judge, limit, page)
if cached is not None:
 cached["cached"] = True
 return cached

# ... existing search logic ...

# Before the final return, add:
result["cached"] = False
set_cached(result, query, court, from_date, to_date, judge, limit, page)
return result
```

#### C. Add `data/cache/` to `.gitignore`

Add `data/cache/` to `.gitignore` so cached results aren't committed.

**Expected benefit:** Repeated queries (same or similar) return instantly from disk instead of making HTTP calls. Most useful for common legal propositions that are searched repeatedly.

---

## Cleanup Tasks

After both patches are applied:

| File | Action |
|------|--------|
| `/tmp/apply_concurrency_patch.py` | Delete |
| `/tmp/patch_runner.py` | Delete |
| `/tmp/apply_p.py` | Delete |

---

## Verification Steps

After each change:

```bash
# 1. Syntax check
python3 -c "import ast; ast.parse(open('legal_mcp_server/src/tools/research_tools.py').read()); print('OK')"

# 2. Run existing tests
cd legal_mcp_server && python3 -m pytest tests/ -x -q

# 3. Check git status
git diff --stat
```

---

## Priority Order

1. **Patch 1 (asyncio.gather)** — highest impact, zero new dependencies, apply first
2. **Patch 2 (file cache)** — add after Patch 1 is verified working
3. **Cleanup** — remove temp files last
