#!/usr/bin/env python3
"""Extract judgment text into the full-text (topical) search index.

Indexes the newest not-yet-indexed judgments of the chosen courts first and
commits every batch, so it can be stopped at any time and re-run to resume.
Needs the metadata index (`make fts`) first. See docs/full-text-search.md.

Usage:
    uv run python scripts/build_body_index.py [--court SC --court Bombay]
        [--limit N] [--workers 4] [--concurrency 16]
"""

from __future__ import annotations

import argparse
import asyncio
import traceback

from legal_mcp_server.src.sources import body_index, open_judgments


def main() -> None:
    """Parse CLI arguments and extend the body-text index."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--court",
        action="append",
        help="Court name or code; repeatable. Default: Supreme Court and Bombay.",
    )
    parser.add_argument("--limit", type=int, help="Stop after N new judgments.")
    parser.add_argument("--workers", type=int, default=4, help="Extraction processes.")
    parser.add_argument(
        "--concurrency", type=int, default=16, help="Simultaneous PDF downloads."
    )
    args = parser.parse_args()

    async def run() -> dict:
        client = open_judgments.get_client()
        try:
            return await body_index.build(
                client,
                courts=args.court,
                limit=args.limit,
                workers=args.workers,
                concurrency=args.concurrency,
            )
        finally:
            await client.aclose()

    try:
        result = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - report and fail loudly
        traceback.print_exc()
        raise SystemExit(1) from exc
    print(result["message"], f"total={result['total_indexed']}", flush=True)


if __name__ == "__main__":
    main()
