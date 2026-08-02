"""Pluggable embedding providers for document search.

Three backends, selected by ``EMBEDDING_PROVIDER``:

``voyage``
    Voyage AI's ``voyage-law-2``, trained on legal text and markedly better on
    Indian judgments and contracts than a general-purpose model. Needs
    ``VOYAGE_API_KEY`` and the ``voyage`` extra.
``local``
    fastembed, running offline on CPU. No key, no data leaving the machine.
    Needs the ``local`` extra.
``disabled``
    No embeddings. Document search falls back to Postgres full-text, which is
    reported to the caller rather than silently substituted.

Both real backends are optional dependencies, so a missing package produces a
clear, actionable error rather than an import failure at server start.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from legal_mcp_server.src.settings import settings
from legal_mcp_server.utils.pylogger import get_python_logger

logger = get_python_logger()


class EmbeddingUnavailable(RuntimeError):
    """Raised when embeddings are requested but cannot be produced."""


class EmbeddingProvider(ABC):
    """Interface every embedding backend implements."""

    name: str = "abstract"
    dimensions: int = 0

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed passages for storage."""

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Embed a search query."""


class VoyageProvider(EmbeddingProvider):
    """Voyage AI embeddings, defaulting to the legal-domain voyage-law-2 model."""

    name = "voyage"

    def __init__(self) -> None:
        """Create the provider, validating configuration eagerly."""
        if not settings.VOYAGE_API_KEY:
            raise EmbeddingUnavailable(
                "EMBEDDING_PROVIDER is 'voyage' but VOYAGE_API_KEY is not set."
            )
        try:
            import voyageai
        except ImportError as e:
            raise EmbeddingUnavailable(
                "The voyageai package is not installed. Install it with "
                "'uv pip install -e \".[voyage]\"', or set "
                "EMBEDDING_PROVIDER=local or disabled."
            ) from e

        self._client = voyageai.AsyncClient(api_key=settings.VOYAGE_API_KEY)
        self._model = settings.EMBEDDING_MODEL
        self.dimensions = settings.EMBEDDING_DIMENSIONS

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed passages with the document input type."""
        result = await self._client.embed(
            texts, model=self._model, input_type="document"
        )
        return result.embeddings

    async def embed_query(self, text: str) -> List[float]:
        """Embed a query with the query input type."""
        result = await self._client.embed([text], model=self._model, input_type="query")
        return result.embeddings[0]


class LocalProvider(EmbeddingProvider):
    """Offline embeddings via fastembed. No network, no key, no data egress."""

    name = "local"

    def __init__(self) -> None:
        """Create the provider, loading the model lazily on first use."""
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise EmbeddingUnavailable(
                "The fastembed package is not installed. Install it with "
                "'uv pip install -e \".[local]\"', or set "
                "EMBEDDING_PROVIDER=voyage or disabled."
            ) from e

        model_name = (
            settings.EMBEDDING_MODEL
            if settings.EMBEDDING_MODEL.startswith(("BAAI/", "sentence-transformers/"))
            else "BAAI/bge-small-en-v1.5"
        )
        self._model = TextEmbedding(model_name=model_name)
        self.dimensions = settings.EMBEDDING_DIMENSIONS
        logger.info(f"Local embedding model loaded: {model_name}")

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed passages on the local CPU."""
        return [list(map(float, v)) for v in self._model.embed(texts)]

    async def embed_query(self, text: str) -> List[float]:
        """Embed a query on the local CPU."""
        return list(map(float, next(iter(self._model.embed([text])))))


_provider: Optional[EmbeddingProvider] = None
_provider_error: Optional[str] = None


def get_provider() -> Optional[EmbeddingProvider]:
    """Return the configured provider, or None when embeddings are disabled.

    Raises:
        EmbeddingUnavailable: If a provider is configured but cannot be built.
    """
    global _provider, _provider_error

    if settings.EMBEDDING_PROVIDER == "disabled":
        return None
    if _provider is not None:
        return _provider
    if _provider_error is not None:
        raise EmbeddingUnavailable(_provider_error)

    try:
        if settings.EMBEDDING_PROVIDER == "voyage":
            _provider = VoyageProvider()
        else:
            _provider = LocalProvider()
    except EmbeddingUnavailable as e:
        _provider_error = str(e)
        raise

    return _provider


def reset_provider() -> None:
    """Drop the cached provider. Used by tests and after a settings change."""
    global _provider, _provider_error
    _provider = None
    _provider_error = None


def provider_status() -> dict:
    """Describe the embedding configuration for tool output."""
    if settings.EMBEDDING_PROVIDER == "disabled":
        return {
            "provider": "disabled",
            "semantic_search": False,
            "note": (
                "Embeddings are disabled, so document search uses Postgres "
                "full-text matching only. Exact terms and citations work well; "
                "conceptual queries such as 'the clause about early exit' will "
                "not. Set EMBEDDING_PROVIDER=local for offline semantic search."
            ),
        }

    try:
        provider = get_provider()
        return {
            "provider": settings.EMBEDDING_PROVIDER,
            "model": settings.EMBEDDING_MODEL,
            "dimensions": provider.dimensions if provider else 0,
            "semantic_search": True,
            "note": None,
        }
    except EmbeddingUnavailable as e:
        return {
            "provider": settings.EMBEDDING_PROVIDER,
            "semantic_search": False,
            "error": str(e),
            "note": (
                "An embedding provider is configured but unusable, so search has "
                "fallen back to full-text only."
            ),
        }
