#!/usr/bin/env python3
"""Build the BM25 full-text index over the synced case-law corpus.

The search tool uses this index for ranked full-text search when it is present
and fresh, falling back to a LIKE scan otherwise. Rebuild it after any
`sync_case_law` run that changed the corpus, or use the `--force` flag to
rebuild unconditionally.

Usage:
    uv run python scripts/build_fts_index.py [--force]
"""

from __future__ import annotations

import argparse
import traceback

from legal_mcp_server.src.sources import open_judgments


def main() -> None:
    """Parse CLI arguments and build (or refresh) the FTS index.

    Progress is logged to stderr as the build runs (parquet scan, corpus
    table, BM25 index, commit) so an unattended run always leaves a trail;
    failures exit non-zero with the traceback.
    """
    parser = argparse.ArgumentParser(
        description="Build the BM25 full-text index over synced case law."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the index already looks fresh.",
    )
    args = parser.parse_args()

    try:
        client = open_judgments.get_client()
        result = client.build_fts_index(force=args.force)
    except Exception as exc:  # noqa: BLE001 - report and fail loudly
        traceback.print_exc()
        raise SystemExit(1) from exc

    if result["status"] != "success":
        raise SystemExit(f"FTS build failed: {result}")
    elapsed = result.get("elapsed_seconds", "?")
    print(
        f"status={result['status']} rows={result['rows']} "
        f"rebuilt={result['rebuilt']} elapsed={elapsed}s path={result['path']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
