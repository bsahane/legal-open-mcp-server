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

from legal_mcp_server.src.sources import open_judgments


def main() -> None:
    """Parse CLI arguments and build (or refresh) the FTS index."""
    parser = argparse.ArgumentParser(
        description="Build the BM25 full-text index over synced case law."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the index already looks fresh.",
    )
    args = parser.parse_args()

    client = open_judgments.get_client()
    result = client.build_fts_index(force=args.force)
    if result["status"] != "success":
        raise SystemExit(f"FTS build failed: {result}")
    print(
        f"status={result['status']} rows={result['rows']} "
        f"rebuilt={result['rebuilt']} path={result['path']}"
    )


if __name__ == "__main__":
    main()
