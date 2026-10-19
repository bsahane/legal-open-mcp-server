"""Tests for full-text (topical) search over extracted judgment text.

Real PDFs with a text layer are generated in memory, so download, extraction,
indexing and BM25 search are all genuinely exercised; only HTTP is mocked.
"""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from test_open_judgments import corpus  # noqa: F401 - pytest fixture

from legal_mcp_server.src.sources import body_index, case_law, open_judgments
from legal_mcp_server.src.tools import research_tools

FILLER = " The Court heard counsel for both sides at length on the record." * 5
TEXTS = {
    "2024_10_108_125": "Murder appeal. Section 302 IPC. Conviction set aside." + FILLER,
    "2024_5_629_729": (
        "Anticipatory bail granted on the ground of parity with co-accused." + FILLER
    ),
    "HCBM05000392_1_2024-04-25.pdf": (
        "Application for anticipatory bail rejected; parity does not apply." + FILLER
    ),
}


def _pdf(text: str) -> bytes:
    """A minimal one-page PDF whose text layer is ``text``."""
    stream = f"BT /F1 10 Tf 20 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


def _http(urls):
    """Mock S3: serve the PDF whose name the URL ends with, 404 otherwise."""

    async def get(_client, url):
        urls.append(url)
        for name, text in TEXTS.items():
            if url.endswith(name) or url.endswith(name + "_EN.pdf"):
                return SimpleNamespace(
                    status_code=200, content=_pdf(text), raise_for_status=lambda: None
                )
        return SimpleNamespace(status_code=404, content=b"")

    return get


@pytest.fixture
async def indexed(corpus):  # noqa: F811 - the imported fixture
    """The fixture corpus with both indexes built."""
    corpus.build_fts_index()
    urls = []
    with patch.object(corpus, "_get_with_retry", side_effect=_http(urls)):
        result = await body_index.build(corpus, workers=1)
    yield corpus, result, urls


class TestBuild:
    """The builder extracts, records and resumes."""

    async def test_indexes_every_judgment_of_the_default_courts(self, indexed):
        _client, result, urls = indexed
        assert result["status"] == "success"
        assert result["indexed"] == 3
        assert result["total_indexed"] == 3
        assert len(urls) == 3

    async def test_rerun_fetches_nothing(self, indexed):
        client, _result, _urls = indexed
        get = AsyncMock()
        with patch.object(client, "_get_with_retry", get):
            again = await body_index.build(client, workers=1)
        assert again["indexed"] == 0
        get.assert_not_called()

    async def test_missing_and_failed_pdfs(self, corpus):  # noqa: F811
        corpus.build_fts_index()

        async def get(_client, url):
            if "2024_10_108_125" in url:
                raise open_judgments.SourceUnavailable("throttled")
            return SimpleNamespace(status_code=404, content=b"")

        with patch.object(corpus, "_get_with_retry", side_effect=get):
            result = await body_index.build(corpus, workers=1)
        # The failure is retried next run; the 404s are recorded as textless.
        assert (result["indexed"], result["without_text"], result["failed"]) == (
            0,
            2,
            1,
        )

    async def test_cached_pdf_is_used_and_limit_respected(self, corpus):  # noqa: F811
        corpus.build_fts_index()
        doc_id = "hc:27_1:hcbgoa:2024:HCBM05000392_1_2024-04-25.pdf"
        corpus.pdf_cache_dir.mkdir(parents=True)
        cached = corpus.pdf_cache_dir / (doc_id.replace(":", "_") + ".pdf")
        cached.write_bytes(_pdf(TEXTS["HCBM05000392_1_2024-04-25.pdf"]))
        get = AsyncMock()
        with patch.object(corpus, "_get_with_retry", get):
            result = await body_index.build(corpus, courts=["Bombay"], limit=1)
        assert result["indexed"] == 1
        get.assert_not_called()

    async def test_needs_the_metadata_index(self, corpus):  # noqa: F811
        with pytest.raises(open_judgments.SourceUnavailable, match="make fts"):
            await body_index.build(corpus)


class TestSearch:
    """Topical queries hit judgment text, with the usual filters."""

    async def test_topical_query_finds_text_not_in_metadata(self, indexed):
        client, _, _ = indexed
        hits = await body_index.search(client, '"anticipatory bail" parity')
        assert {h["doc_id"] for h in hits} == {
            "sc:2024:2024_5_629_729",
            "hc:27_1:hcbgoa:2024:HCBM05000392_1_2024-04-25.pdf",
        }

    async def test_words_are_stemmed(self, indexed):
        client, _, _ = indexed
        hits = await body_index.search(client, "grants")
        assert [h["doc_id"] for h in hits] == ["sc:2024:2024_5_629_729"]

    async def test_filters(self, indexed):
        client, _, _ = indexed
        q = "anticipatory bail"
        bombay = await body_index.search(client, q, court="Bombay High Court")
        assert [h["court"] for h in bombay] == ["Bombay High Court"]
        assert await body_index.search(client, q, from_date="2024-06-01") == []
        assert await body_index.search(client, q, to_date="2024-01-01") == []
        dhulia = await body_index.search(client, q, judge="dhulia")
        assert [h["doc_id"] for h in dhulia] == ["sc:2024:2024_5_629_729"]
        assert await body_index.search(client, "!!") == []

    async def test_unbuilt_index_is_reported(self, corpus):  # noqa: F811
        with pytest.raises(open_judgments.SourceUnavailable, match="not been built"):
            await body_index.search(corpus, "bail")
        assert body_index.covered_courts(corpus) == {}
        assert body_index.version(corpus) == "0"


class TestTool:
    """search_case_law(full_text=True) is gated by the setting."""

    async def test_disabled_by_default(self, indexed, tmp_path):
        with patch.object(
            open_judgments.settings, "LEGAL_DATA_PATH", str(tmp_path / "cache")
        ):
            result = await research_tools.search_case_law(
                "anticipatory bail", full_text=True
            )
        assert result["status"] == "unavailable"
        assert "CASE_LAW_FULL_TEXT_SEARCH" in result["error"]

    async def test_enabled(self, indexed, tmp_path):
        from legal_mcp_server.src import cache as cache_mod

        with (
            patch.object(
                open_judgments.settings, "LEGAL_DATA_PATH", str(tmp_path / "cache")
            ),
            patch.object(case_law.settings, "CASE_LAW_FULL_TEXT_SEARCH", True),
        ):
            cache_mod._get_cache.cache_clear()
            try:
                meta = await research_tools.search_case_law("parity")
                text = await research_tools.search_case_law("parity", full_text=True)
                again = await research_tools.search_case_law("parity", full_text=True)
            finally:
                cache_mod._get_cache.cache_clear()
            status = case_law.status()
        assert meta["result_count"] == 0
        assert text["status"] == "success"
        assert text["result_count"] == 2
        assert "Supreme Court of India (2)" in text["scope_note"]
        assert again["cached"] is True
        assert status["full_text_index"] == {
            "Bombay High Court": 1,
            "Supreme Court of India": 2,
        }


async def test_covered_courts_is_cached_per_index_version(indexed):
    client, _, _ = indexed
    body_index._covered.cache_clear()
    assert body_index.covered_courts(client)["Supreme Court of India"] == 2
    body_index.covered_courts(client)
    assert body_index._covered.cache_info().hits == 1
    path = body_index.index_path(client)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
    body_index.covered_courts(client)
    assert body_index._covered.cache_info().misses == 2
