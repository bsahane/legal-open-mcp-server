"""Tests for the network-facing half of the open-data backend.

The S3 listing, the metadata sync, PDF retrieval and text extraction all reach
the network in production. Here ``httpx`` is replaced with a fake that serves
canned S3 XML and PDF bytes, so the pagination, key-to-path mapping, caching and
failure handling are exercised without a single real request.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest

from legal_mcp_server.src.sources import case_law, open_judgments

NS = 'xmlns="http://s3.amazonaws.com/doc/2006-03-01/"'


def _list_xml(
    keys: List[str], truncated: bool = False, token: Optional[str] = None
) -> str:
    """Build an S3 ListObjectsV2 response."""
    contents = "".join(
        f"<Contents><Key>{k}</Key><Size>{100 + i}</Size></Contents>"
        for i, k in enumerate(keys)
    )
    extra = ""
    if truncated:
        extra = (
            "<IsTruncated>true</IsTruncated>"
            f"<NextContinuationToken>{token}</NextContinuationToken>"
        )
    else:
        extra = "<IsTruncated>false</IsTruncated>"
    return f"<?xml version='1.0'?><ListBucketResult {NS}>{contents}{extra}</ListBucketResult>"


class FakeResponse:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, text: str = "", content: bytes = b"", status_code: int = 200):
        self.text = text
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Async context-manager client that dispatches to a handler function."""

    def __init__(self, handler):
        self._handler = handler
        self.calls: List[Any] = []

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_exc: Any) -> bool:
        return False

    async def get(self, url: str, params: Optional[Dict[str, str]] = None):
        self.calls.append((url, params))
        return self._handler(url, params)


def _patch_httpx(handler):
    """Patch the httpx module used by open_judgments with a fake."""
    client = FakeClient(handler)
    fake = SimpleNamespace(AsyncClient=lambda **_kw: client)
    return patch.object(open_judgments, "httpx", fake), client


class TestListKeys:
    """S3 listing must follow continuation tokens or it silently truncates."""

    @pytest.mark.asyncio
    async def test_single_page(self, tmp_path: Path):
        def handler(url, params):
            return FakeResponse(text=_list_xml(["a/1.parquet", "a/2.parquet"]))

        patcher, client = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            keys = await c._list_keys("bucket", "a/", client)

        assert [k for k, _ in keys] == ["a/1.parquet", "a/2.parquet"]

    @pytest.mark.asyncio
    async def test_follows_continuation_token(self, tmp_path: Path):
        pages = [
            _list_xml(["p1"], truncated=True, token="TOK1"),
            _list_xml(["p2"], truncated=False),
        ]
        seen_tokens: List[Optional[str]] = []

        def handler(url, params):
            seen_tokens.append((params or {}).get("continuation-token"))
            return FakeResponse(text=pages[len(seen_tokens) - 1])

        patcher, client = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            keys = await c._list_keys("bucket", "p", client)

        assert [k for k, _ in keys] == ["p1", "p2"]
        assert seen_tokens == [None, "TOK1"]

    @pytest.mark.asyncio
    async def test_stops_when_token_missing_despite_truncated_flag(
        self, tmp_path: Path
    ):
        """A truncated response with no token must not loop forever."""
        xml = (
            f"<?xml version='1.0'?><ListBucketResult {NS}>"
            "<Contents><Key>x</Key><Size>1</Size></Contents>"
            "<IsTruncated>true</IsTruncated>"
            "</ListBucketResult>"
        )

        def handler(url, params):
            return FakeResponse(text=xml)

        patcher, client = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            keys = await c._list_keys("bucket", "x", client)

        assert [k for k, _ in keys] == ["x"]


class TestSync:
    """Sync writes metadata to the hive-partitioned layout it later queries."""

    @pytest.mark.asyncio
    async def test_sync_supreme_court_writes_expected_path(self, tmp_path: Path):
        def handler(url, params):
            if params:
                return FakeResponse(
                    text=_list_xml(
                        [
                            "metadata/parquet/year=2023/metadata.parquet",
                            "metadata/parquet/year=2024/metadata.parquet",
                        ]
                    )
                )
            return FakeResponse(content=b"PARQUETBYTES")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            summary = await c.sync(["Supreme Court"], 2024, 2024)

        written = tmp_path / "sc" / "metadata" / "year=2024" / "metadata.parquet"
        assert written.exists()
        assert written.read_bytes() == b"PARQUETBYTES"
        # 2023 was outside the requested range and must not be fetched.
        assert not (tmp_path / "sc" / "metadata" / "year=2023").exists()
        assert summary["files"] == 1
        assert "CC-BY-4.0" in summary["attribution"]

    @pytest.mark.asyncio
    async def test_sync_high_court_includes_bench_in_path(self, tmp_path: Path):
        def handler(url, params):
            if params:
                return FakeResponse(
                    text=_list_xml(
                        [
                            "metadata/parquet/year=2024/court=27_1/bench=hcbgoa/metadata.parquet",
                            "metadata/parquet/year=2024/court=27_1/bench=hcbgoa/metadata-mobile.parquet",
                        ]
                    )
                )
            return FakeResponse(content=b"HC")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            summary = await c.sync(["Bombay High Court"], 2024, 2024)

        target = (
            tmp_path
            / "hc"
            / "metadata"
            / "year=2024"
            / "court=27_1"
            / "bench=hcbgoa"
            / "metadata.parquet"
        )
        assert target.exists()
        # The -mobile sidecar is deliberately skipped as non-canonical.
        assert summary["files"] == 1
        assert "hcbgoa" in summary["courts"]["Bombay High Court"]["benches"]

    @pytest.mark.asyncio
    async def test_existing_file_is_skipped_not_refetched(self, tmp_path: Path):
        downloads = {"count": 0}

        def handler(url, params):
            if params:
                return FakeResponse(
                    text=_list_xml(["metadata/parquet/year=2024/metadata.parquet"])
                )
            downloads["count"] += 1
            return FakeResponse(content=b"DATA")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            first = await c.sync(["Supreme Court"], 2024, 2024)
            second = await c.sync(["Supreme Court"], 2024, 2024)

        assert first["files"] == 1
        assert second["files"] == 0
        assert second["skipped"] == 1
        assert downloads["count"] == 1

    @pytest.mark.asyncio
    async def test_force_redownloads(self, tmp_path: Path):
        downloads = {"count": 0}

        def handler(url, params):
            if params:
                return FakeResponse(
                    text=_list_xml(["metadata/parquet/year=2024/metadata.parquet"])
                )
            downloads["count"] += 1
            return FakeResponse(content=b"DATA")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            await c.sync(["Supreme Court"], 2024, 2024)
            again = await c.sync(["Supreme Court"], 2024, 2024, force=True)

        assert again["files"] == 1
        assert downloads["count"] == 2

    @pytest.mark.asyncio
    async def test_unknown_court_is_rejected_before_any_request(self, tmp_path: Path):
        def handler(url, params):  # pragma: no cover - must never be reached
            raise AssertionError("no request should be made")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with patcher:
            with pytest.raises(open_judgments.SourceUnavailable):
                await c.sync(["Nowhere High Court"], 2024, 2024)


class TestJudgmentRetrieval:
    """PDF fetch, cache reuse, text extraction and the failure modes."""

    @pytest.mark.asyncio
    async def test_fetches_caches_and_extracts(self, tmp_path: Path):
        requests = {"count": 0}

        def handler(url, params):
            requests["count"] += 1
            return FakeResponse(content=b"%PDF-fake")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))

        with patcher, patch.object(
            open_judgments.OpenJudgmentsClient,
            "_extract_pdf_text",
            staticmethod(lambda _p: "JUDGMENT TEXT"),
        ):
            first = await c.get_judgment("sc:2024:2024_10_108_125")
            second = await c.get_judgment("sc:2024:2024_10_108_125")

        assert first.text == "JUDGMENT TEXT"
        assert second.text == "JUDGMENT TEXT"
        # Second call is served from the on-disk cache.
        assert requests["count"] == 1
        assert first.url.endswith("_EN.pdf")

    @pytest.mark.asyncio
    async def test_missing_pdf_is_reported_not_silently_empty(self, tmp_path: Path):
        def handler(url, params):
            return FakeResponse(status_code=404)

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))

        with patcher:
            with pytest.raises(open_judgments.SourceUnavailable) as exc:
                await c.get_judgment("sc:2024:2024_10_108_125")

        assert "No PDF published" in str(exc.value)

    @pytest.mark.asyncio
    async def test_high_court_pdf_url_uses_bench_directory(self, tmp_path: Path):
        seen: List[str] = []

        def handler(url, params):
            seen.append(url)
            return FakeResponse(content=b"%PDF-fake")

        patcher, _ = _patch_httpx(handler)
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))

        with patcher, patch.object(
            open_judgments.OpenJudgmentsClient,
            "_extract_pdf_text",
            staticmethod(lambda _p: "text"),
        ):
            await c.get_judgment("hc:27_1:hcbgoa:2024:FILE.pdf")

        assert "court=27_1/bench=hcbgoa/FILE.pdf" in seen[0]
        assert "indian-high-court-judgments" in seen[0]

    @pytest.mark.parametrize(
        "bad_id",
        ["", "nonsense", "sc:2024", "hc:27_1:only:three", "xx:1:2:3:4"],
    )
    @pytest.mark.asyncio
    async def test_malformed_doc_ids_rejected(self, tmp_path: Path, bad_id: str):
        c = open_judgments.OpenJudgmentsClient(data_path=str(tmp_path))
        with pytest.raises(open_judgments.SourceUnavailable):
            c._parse_doc_id(bad_id)

    def test_scanned_pdf_says_so_instead_of_returning_nothing(self, tmp_path: Path):
        """An image-only judgment must be flagged, not returned as empty text."""
        pdf = tmp_path / "scan.pdf"
        pdf.write_bytes(b"%PDF-fake")

        fake_reader = Mock()
        fake_reader.pages = [Mock(extract_text=Mock(return_value=""))]

        with patch.dict(
            "sys.modules",
            {"pypdf": SimpleNamespace(PdfReader=lambda _p: fake_reader)},
        ):
            text = open_judgments.OpenJudgmentsClient._extract_pdf_text(pdf)

        assert "scanned" in text.lower()

    def test_extracts_and_joins_pages(self, tmp_path: Path):
        pdf = tmp_path / "ok.pdf"
        pdf.write_bytes(b"%PDF-fake")

        fake_reader = Mock()
        fake_reader.pages = [
            Mock(extract_text=Mock(return_value="page one")),
            Mock(extract_text=Mock(return_value="  ")),
            Mock(extract_text=Mock(return_value="page two")),
        ]

        with patch.dict(
            "sys.modules",
            {"pypdf": SimpleNamespace(PdfReader=lambda _p: fake_reader)},
        ):
            text = open_judgments.OpenJudgmentsClient._extract_pdf_text(pdf)

        assert text == "page one\n\npage two"


class TestPartyTermExtraction:
    """Related-proceedings lookup depends on pulling usable party words out."""

    def test_drops_case_number_prefix_and_stopwords(self):
        terms = case_law._party_terms(
            "MCA/130/2024 of ANGELA CASTELINO Vs VILAS SHANKAR NAIK AND 27 ORS.,"
        )
        assert "ANGELA" in terms
        assert all(t.lower() not in {"ors", "and", "of"} for t in terms)

    def test_handles_versus_spelling(self):
        assert case_law._party_terms("SHARMA versus THE STATE OF BIHAR")

    def test_empty_title_yields_nothing(self):
        assert case_law._party_terms("") == []

    def test_generic_parties_are_filtered_out(self):
        """A title of only generic words gives no usable search terms."""
        assert case_law._party_terms("STATE OF INDIA Vs UNION OF INDIA") == []


class TestPaidBackendDispatch:
    """The paid backend stays reachable for anyone who opts in."""

    @pytest.mark.asyncio
    async def test_search_routes_to_indian_kanoon(self):
        fake = Mock()
        fake.search = AsyncMock(
            return_value={"results": [{"doc_id": 1}], "found": "1", "query": "q", "page": 0}
        )
        fake.spend_report = Mock(return_value={"spent_inr": 0.5})

        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "indian_kanoon"):
            with patch(
                "legal_mcp_server.src.sources.indian_kanoon.get_client",
                return_value=fake,
            ):
                payload = await case_law.search("query")

        assert payload["backend"] == "indian_kanoon"
        assert "billed" in payload["cost"]
        assert payload["spend"]["spent_inr"] == 0.5

    @pytest.mark.asyncio
    async def test_citator_is_real_on_paid_backend(self):
        judgment = Mock(cited_by=[{"doc_id": 9}])
        fake = Mock()
        fake.get_document = AsyncMock(return_value=judgment)

        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "indian_kanoon"):
            with patch(
                "legal_mcp_server.src.sources.indian_kanoon.get_client",
                return_value=fake,
            ):
                payload = await case_law.find_related_proceedings("123")

        assert payload["is_citator"] is True

    @pytest.mark.asyncio
    async def test_status_reports_paid_backend(self):
        fake = Mock(available=True)
        fake.spend_report = Mock(return_value={"spent_inr": 1.0})

        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "indian_kanoon"):
            with patch(
                "legal_mcp_server.src.sources.indian_kanoon.get_client",
                return_value=fake,
            ):
                payload = case_law.status()

        assert payload["backend"] == "indian_kanoon"
        assert payload["available"] is True

    def test_status_reports_disabled_backend(self):
        with patch.object(case_law.settings, "CASE_LAW_SOURCE", "disabled"):
            payload = case_law.status()
        assert payload["available"] is False


class TestClientSingleton:
    """The module-level client is reused, and resettable for tests."""

    def test_get_client_is_stable(self):
        open_judgments.reset_client()
        assert open_judgments.get_client() is open_judgments.get_client()

    def test_reset_client_clears_it(self):
        first = open_judgments.get_client()
        open_judgments.reset_client()
        assert open_judgments.get_client() is not first
