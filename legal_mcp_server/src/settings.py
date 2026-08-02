"""Settings for the Legal MCP Server."""

from functools import cached_property
from typing import List, Literal, Optional

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from legal_mcp_server.utils.pylogger import get_python_logger

# Initialize logger
logger = get_python_logger()

# Load environment variables with error handling
try:
    load_dotenv()
except Exception as e:
    # Log error but don't fail - environment variables might be set directly
    logger.warning(f"Could not load .env file: {e}")


def parse_sso_scopes(sso_scopes: str) -> list[str]:
    """Parse comma-separated SSO_SCOPES into a list of non-empty scope strings."""
    raw = sso_scopes or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


def validate_sso_scopes(enable_auth: bool, sso_scopes: str) -> None:
    """Validate SSO_SCOPES according to auth mode."""
    if enable_auth and not parse_sso_scopes(sso_scopes):
        raise ValueError(
            "SSO_SCOPES must contain at least one OAuth scope when ENABLE_AUTH is True "
            '(comma-separated, e.g. "email,openid,profile").'
        )


class Settings(BaseSettings):
    """Configuration settings for the Legal MCP Server.

    Uses Pydantic BaseSettings to load and validate configuration from environment variables.
    Provides default values for optional settings and validation for required ones.
    """

    MCP_HOST: str = Field(
        default="localhost",
        json_schema_extra={
            "env": "MCP_HOST",
            "description": "Host address for the MCP server",
            "example": "localhost",
        },
    )
    MCP_PORT: int = Field(
        default=5001,
        ge=1024,
        le=65535,
        json_schema_extra={
            "env": "MCP_PORT",
            "description": "Port number for the MCP server",
            "example": 5001,
        },
    )
    MCP_SSL_KEYFILE: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "MCP_SSL_KEYFILE",
            "description": "Path to SSL private key file for HTTPS",
            "example": "/path/to/key.pem",
        },
    )
    MCP_SSL_CERTFILE: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "MCP_SSL_CERTFILE",
            "description": "Path to SSL certificate file for HTTPS",
            "example": "/path/to/cert.pem",
        },
    )
    MCP_TRANSPORT_PROTOCOL: str = Field(
        default="http",
        json_schema_extra={
            "env": "MCP_TRANSPORT_PROTOCOL",
            "description": "Transport protocol for the MCP server",
            "example": "streamable-http",
            "enum": ["streamable-http", "sse", "http"],
        },
    )
    PYTHON_LOG_LEVEL: str = Field(
        default="INFO",
        json_schema_extra={
            "env": "PYTHON_LOG_LEVEL",
            "description": "Logging level for the application",
            "example": "INFO",
            "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        },
    )
    CORS_ENABLED: bool = Field(
        default=False,
        json_schema_extra={
            "env": "CORS_ENABLED",
            "description": "Enable CORS for the MCP server",
            "example": True,
        },
    )
    CORS_ORIGINS: List[str] = Field(
        default=["*"],
        json_schema_extra={
            "env": "CORS_ORIGINS",
            "description": "Origins allowed to access the MCP server",
            "example": ["*"],
        },
    )
    CORS_CREDENTIALS: bool = Field(
        default=True,
        json_schema_extra={
            "env": "CORS_CREDENTIALS",
            "description": "Allow credentials for CORS requests",
            "example": True,
        },
    )
    CORS_METHODS: List[str] = Field(
        default=["*"],
        json_schema_extra={
            "env": "CORS_METHODS",
            "description": "Methods allowed for CORS requests",
            "example": ["*"],
        },
    )
    CORS_HEADERS: List[str] = Field(
        default=["*"],
        json_schema_extra={
            "env": "CORS_HEADERS",
            "description": "Headers allowed for CORS requests",
            "example": ["*"],
        },
    )
    SSO_CLIENT_ID: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_CLIENT_ID",
            "description": "Client ID for the SSO",
            "example": "1234567890",
        },
    )
    SSO_CLIENT_SECRET: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_CLIENT_SECRET",
            "description": "Client secret for the SSO",
            "example": "1234567890",
        },
    )
    SSO_CALLBACK_URL: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_CALLBACK_URL",
            "description": "Callback URL for the SSO",
            "example": "http://localhost:3000/auth/callback",
        },
    )
    SSO_AUTHORIZATION_URL: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_AUTHORIZATION_URL",
            "description": "SSO authorization endpoint URL",
        },
    )
    SSO_TOKEN_URL: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_TOKEN_URL",
            "description": "SSO token endpoint URL",
        },
    )
    SSO_INTROSPECTION_URL: str = Field(
        default="",
        json_schema_extra={
            "env": "SSO_INTROSPECTION_URL",
            "description": "SSO token introspection endpoint URL",
        },
    )
    SSO_INTROSPECTION_MODE: Literal["rfc7662", "tokeninfo"] = Field(
        default="rfc7662",
        json_schema_extra={
            "env": "SSO_INTROSPECTION_MODE",
            "description": (
                "Token validation strategy: rfc7662 (POST introspection) or "
                "tokeninfo (GET access_token query param for providers like Google)"
            ),
            "example": "rfc7662",
            "enum": ["rfc7662", "tokeninfo"],
        },
    )
    SSO_SCOPES: str = Field(
        default="email,openid,profile,session:role-any",
        json_schema_extra={
            "env": "SSO_SCOPES",
            "description": (
                "Comma-separated OAuth scopes to request (e.g. email,openid,profile for Google). "
                "When ENABLE_AUTH is True, at least one non-empty scope is required."
            ),
            "example": "email,openid,profile",
        },
    )
    SESSION_SECRET: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "SESSION_SECRET",
            "description": "Secret key for session middleware (required in production)",
            "example": "your-super-secret-session-key-here",
            "sensitive": True,
        },
    )
    USE_EXTERNAL_BROWSER_AUTH: bool = Field(
        default=False,
        json_schema_extra={
            "env": "USE_EXTERNAL_BROWSER_AUTH",
            "description": "Whether the application is running in local development mode",
            "example": "true",
        },
    )

    # PostgreSQL Configuration
    POSTGRES_HOST: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "POSTGRES_HOST",
            "description": "PostgreSQL host address",
            "example": "localhost",
        },
    )
    POSTGRES_PORT: Optional[int] = Field(
        default=None,
        ge=1024,
        le=65535,
        json_schema_extra={
            "env": "POSTGRES_PORT",
            "description": "PostgreSQL port number",
            "example": 5432,
        },
    )
    POSTGRES_DB: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "POSTGRES_DB",
            "description": "PostgreSQL database name",
            "example": "legal_mcp_server",
        },
    )
    POSTGRES_USER: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "POSTGRES_USER",
            "description": "PostgreSQL username",
            "example": "postgres",
        },
    )
    POSTGRES_PASSWORD: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "POSTGRES_PASSWORD",
            "description": "PostgreSQL password",
            "example": "secretpassword",
            "sensitive": True,
        },
    )
    POSTGRES_POOL_SIZE: int = Field(
        default=10,
        ge=1,
        le=100,
        json_schema_extra={
            "env": "POSTGRES_POOL_SIZE",
            "description": "PostgreSQL connection pool minimum size",
            "example": 10,
        },
    )
    POSTGRES_MAX_CONNECTIONS: int = Field(
        default=20,
        ge=1,
        le=200,
        json_schema_extra={
            "env": "POSTGRES_MAX_CONNECTIONS",
            "description": "PostgreSQL connection pool maximum size",
            "example": 20,
        },
    )
    MCP_HOST_ENDPOINT: str = Field(
        default="http://localhost:5001",
        json_schema_extra={
            "env": "MCP_HOST_ENDPOINT",
            "description": "Host endpoint for the MCP server",
            "example": "http://localhost:5001",
        },
    )
    ENVIRONMENT: str = Field(
        default="development",
        json_schema_extra={
            "env": "ENVIRONMENT",
            "description": "Environment for the MCP server",
            "example": "development",
        },
    )
    COMPATIBLE_WITH_CURSOR: bool = Field(
        default=False,
        json_schema_extra={
            "env": "COMPATIBLE_WITH_CURSOR",
            "description": "Whether the MCP server is compatible with Cursor OAuth2 flow",
            "example": True,
        },
    )
    ENABLE_AUTH: bool = Field(
        default=True,
        json_schema_extra={
            "env": "ENABLE_AUTH",
            "description": "Enable authentication for the MCP server",
            "example": "true",
        },
    )

    # ------------------------------------------------------------------
    # Legal MCP Server settings
    # ------------------------------------------------------------------
    INDIAN_KANOON_API_KEY: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "INDIAN_KANOON_API_KEY",
            "description": (
                "API token for api.indiankanoon.org. Without it, case-law tools "
                "return a clear 'source unavailable' status instead of guessing."
            ),
            "example": "abcdef1234567890",
            "sensitive": True,
        },
    )
    INDIAN_KANOON_BASE_URL: str = Field(
        default="https://api.indiankanoon.org",
        json_schema_extra={
            "env": "INDIAN_KANOON_BASE_URL",
            "description": "Base URL for the Indian Kanoon API",
            "example": "https://api.indiankanoon.org",
        },
    )
    INDIAN_KANOON_DAILY_BUDGET_INR: float = Field(
        default=100.0,
        ge=0,
        json_schema_extra={
            "env": "INDIAN_KANOON_DAILY_BUDGET_INR",
            "description": (
                "Hard daily spend cap in INR for Indian Kanoon calls. Search costs "
                "Rs 0.50, full document Rs 0.20, fragment Rs 0.05. Set 0 to disable "
                "all paid calls."
            ),
            "example": 100.0,
        },
    )
    ENABLE_CITATION_VERIFICATION: bool = Field(
        default=True,
        json_schema_extra={
            "env": "ENABLE_CITATION_VERIFICATION",
            "description": (
                "When True, citations in memos and drafts are resolved against a "
                "real source and marked UNVERIFIED when they cannot be confirmed."
            ),
            "example": "true",
        },
    )
    ECOURTS_ADAPTER: Literal["manual", "api", "disabled"] = Field(
        default="manual",
        json_schema_extra={
            "env": "ECOURTS_ADAPTER",
            "description": (
                "Case-status backend. 'manual' returns portal URLs and steps for a "
                "human to complete (the official portal is CAPTCHA-gated and is "
                "never automated); 'api' uses a licensed third-party provider; "
                "'disabled' turns the court tools off."
            ),
            "example": "manual",
            "enum": ["manual", "api", "disabled"],
        },
    )
    ECOURTS_API_KEY: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "ECOURTS_API_KEY",
            "description": "API key for the licensed third-party eCourts data provider",
            "example": "eci_live_xxx",
            "sensitive": True,
        },
    )
    ECOURTS_API_BASE_URL: str = Field(
        default="https://api.ecourtsindia.com/v1",
        json_schema_extra={
            "env": "ECOURTS_API_BASE_URL",
            "description": "Base URL for the third-party eCourts data provider",
            "example": "https://api.ecourtsindia.com/v1",
        },
    )
    EMBEDDING_PROVIDER: Literal["voyage", "local", "disabled"] = Field(
        default="disabled",
        json_schema_extra={
            "env": "EMBEDDING_PROVIDER",
            "description": (
                "Embedding backend for document search. 'voyage' uses voyage-law-2 "
                "(legal-domain, needs VOYAGE_API_KEY); 'local' uses fastembed "
                "offline; 'disabled' falls back to Postgres full-text only."
            ),
            "example": "voyage",
            "enum": ["voyage", "local", "disabled"],
        },
    )
    VOYAGE_API_KEY: Optional[str] = Field(
        default=None,
        json_schema_extra={
            "env": "VOYAGE_API_KEY",
            "description": "API key for Voyage AI embeddings",
            "example": "pa-xxx",
            "sensitive": True,
        },
    )
    EMBEDDING_MODEL: str = Field(
        default="voyage-law-2",
        json_schema_extra={
            "env": "EMBEDDING_MODEL",
            "description": "Embedding model name for the selected provider",
            "example": "voyage-law-2",
        },
    )
    EMBEDDING_DIMENSIONS: int = Field(
        default=1024,
        ge=64,
        le=4096,
        json_schema_extra={
            "env": "EMBEDDING_DIMENSIONS",
            "description": (
                "Vector width. Must match the model and the pgvector column; "
                "changing it requires re-running the document migration."
            ),
            "example": 1024,
        },
    )
    DEFAULT_JURISDICTION: str = Field(
        default="IN",
        json_schema_extra={
            "env": "DEFAULT_JURISDICTION",
            "description": "ISO country code for the default legal system",
            "example": "IN",
        },
    )
    DEFAULT_STATE: str = Field(
        default="Maharashtra",
        json_schema_extra={
            "env": "DEFAULT_STATE",
            "description": "Default Indian state for state-specific acts and courts",
            "example": "Maharashtra",
        },
    )
    DEFAULT_HIGH_COURT: str = Field(
        default="Bombay",
        json_schema_extra={
            "env": "DEFAULT_HIGH_COURT",
            "description": "Default High Court for case-law filters and cause lists",
            "example": "Bombay",
        },
    )
    DOCUMENT_STORAGE_PATH: str = Field(
        default="./data/documents",
        json_schema_extra={
            "env": "DOCUMENT_STORAGE_PATH",
            "description": "Directory holding ingested source documents",
            "example": "./data/documents",
        },
    )
    LEGAL_DATA_PATH: str = Field(
        default="./data",
        json_schema_extra={
            "env": "LEGAL_DATA_PATH",
            "description": "Directory holding the bundled offline legal corpus",
            "example": "./data",
        },
    )

    @model_validator(mode="after")
    def validate_oauth_scopes(self) -> "Settings":
        """Validate SSO_SCOPES when auth is enabled."""
        validate_sso_scopes(self.ENABLE_AUTH, self.SSO_SCOPES)
        return self

    @cached_property
    def oauth_scopes(self) -> list[str]:
        """Oauth scopes derived from SSO_SCOPES (computed once per Settings instance)."""
        return parse_sso_scopes(self.SSO_SCOPES)

    @cached_property
    def case_law_available(self) -> bool:
        """Whether paid case-law lookups can actually be performed."""
        return (
            bool(self.INDIAN_KANOON_API_KEY) and self.INDIAN_KANOON_DAILY_BUDGET_INR > 0
        )

    @cached_property
    def semantic_search_available(self) -> bool:
        """Whether vector search is usable, as opposed to full-text only."""
        if self.EMBEDDING_PROVIDER == "disabled":
            return False
        if self.EMBEDDING_PROVIDER == "voyage":
            return bool(self.VOYAGE_API_KEY)
        return True


def validate_config(settings: Settings) -> None:
    """Validate configuration settings.

    Performs validation to ensure required settings are present and values
    are within acceptable ranges.

    Args:
        settings: Settings instance to validate.

    Raises:
        ValueError: If required configuration is missing or invalid.
    """
    # Validate port range
    if not (1024 <= settings.MCP_PORT <= 65535):
        raise ValueError(
            f"MCP_PORT must be between 1024 and 65535, got {settings.MCP_PORT}"
        )

    # Validate log level
    valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if settings.PYTHON_LOG_LEVEL.upper() not in valid_log_levels:
        raise ValueError(
            f"PYTHON_LOG_LEVEL must be one of {valid_log_levels}, got {settings.PYTHON_LOG_LEVEL}"
        )

    # Validate transport protocol
    valid_transport_protocols = ["streamable-http", "sse", "http"]
    if settings.MCP_TRANSPORT_PROTOCOL not in valid_transport_protocols:
        raise ValueError(
            f"MCP_TRANSPORT_PROTOCOL must be one of {valid_transport_protocols}, got {settings.MCP_TRANSPORT_PROTOCOL}"
        )

    validate_sso_scopes(settings.ENABLE_AUTH, settings.SSO_SCOPES)
    validate_legal_config(settings)


def validate_legal_config(settings: Settings) -> None:
    """Validate the legal-domain settings.

    Misconfiguration here degrades tools rather than breaking the server, so
    unusable combinations are warnings; only self-contradictory ones raise.

    Args:
        settings: Settings instance to validate.

    Raises:
        ValueError: If a legal-domain setting is internally inconsistent.
    """
    if settings.ECOURTS_ADAPTER == "api" and not settings.ECOURTS_API_KEY:
        raise ValueError(
            "ECOURTS_ADAPTER='api' requires ECOURTS_API_KEY. "
            "Use ECOURTS_ADAPTER='manual' to work without a paid provider."
        )

    if settings.EMBEDDING_PROVIDER == "voyage" and not settings.VOYAGE_API_KEY:
        raise ValueError(
            "EMBEDDING_PROVIDER='voyage' requires VOYAGE_API_KEY. "
            "Use 'local' for offline embeddings or 'disabled' for full-text search only."
        )

    if not settings.INDIAN_KANOON_API_KEY:
        logger.warning(
            "INDIAN_KANOON_API_KEY is not set - case-law search, judgment retrieval "
            "and citation verification against case law will report themselves as "
            "unavailable rather than returning results."
        )

    if settings.EMBEDDING_PROVIDER == "disabled":
        logger.warning(
            "EMBEDDING_PROVIDER is 'disabled' - document search falls back to "
            "Postgres full-text matching, so semantic queries will be weaker."
        )


# Create config instance without validation (validation happens in main.py)
settings = Settings()
