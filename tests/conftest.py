"""Pytest configuration and common fixtures."""

from unittest.mock import Mock, patch

import pytest

# Fully load duckdb before anything patches sys.modules. duckdb pulls in its
# native ``_duckdb`` extension and several submodules lazily; if that first
# import happens while ``mock_imports`` below has sys.modules patched,
# ``patch.dict`` drops the newly registered ``_duckdb`` entry on exit and later
# attribute access dies with "'_duckdb' is not a package". Importing eagerly
# here means it is already cached in the real sys.modules.
try:  # pragma: no cover - environment dependent
    import duckdb  # noqa: F401
    import duckdb.sqltypes  # noqa: F401
except Exception:  # pragma: no cover - duckdb is optional at import time
    pass


@pytest.fixture
def mock_settings():
    """Provide mock settings for testing."""
    settings = Mock()
    settings.MCP_HOST = "0.0.0.0"
    settings.MCP_PORT = 4000
    settings.MCP_TRANSPORT_PROTOCOL = "streamable-http"
    settings.PYTHON_LOG_LEVEL = "INFO"
    settings.MCP_SSL_KEYFILE = None
    settings.MCP_SSL_CERTFILE = None
    return settings


@pytest.fixture
def mock_logger():
    """Provide mock logger for testing."""
    logger = Mock()
    logger.info = Mock()
    logger.error = Mock()
    logger.warning = Mock()
    logger.debug = Mock()
    logger.critical = Mock()
    return logger


@pytest.fixture
def mock_fastmcp():
    """Provide mock FastMCP for testing."""
    mcp = Mock()
    mcp.tool = Mock()
    mcp.resource = Mock()
    mcp.prompt = Mock()
    mcp.http_app = Mock()
    return mcp


@pytest.fixture
def sample_code():
    """Provide sample code for testing."""
    return """def add(a, b):
    return a + b

def multiply(x, y):
    return x * y"""


@pytest.fixture
def sample_error_response():
    """Provide sample error response for testing."""
    return {
        "status": "error",
        "error": "Test error message",
        "message": "Failed to perform operation",
    }


@pytest.fixture
def sample_success_response():
    """Provide sample success response for testing."""
    return {
        "status": "success",
        "operation": "test_operation",
        "result": 42,
        "message": "Operation completed successfully",
    }


@pytest.fixture
def mock_context():
    """Provide mock MCP context for testing."""
    context = Mock()
    context.info = Mock()
    context.error = Mock()
    context.warning = Mock()
    return context


@pytest.fixture
def mock_path():
    """Provide mock path for file operations."""
    mock_path_instance = Mock()
    mock_path_instance.parent = Mock()
    mock_path_instance.parent.__truediv__ = Mock(return_value=Mock())
    return mock_path_instance


@pytest.fixture
def mock_structlog():
    """Provide mock structlog for testing."""
    mock_structlog = Mock()
    mock_structlog.configure = Mock()
    mock_structlog.get_logger = Mock(return_value=Mock())
    mock_structlog.stdlib = Mock()
    mock_structlog.stdlib.LoggerFactory = Mock()
    mock_structlog.stdlib.BoundLogger = Mock()
    mock_structlog.stdlib.filter_by_level = Mock()
    mock_structlog.stdlib.add_logger_name = Mock()
    mock_structlog.stdlib.add_log_level = Mock()
    mock_structlog.stdlib.PositionalArgumentsFormatter = Mock()
    mock_structlog.processors = Mock()
    mock_structlog.processors.TimeStamper = Mock()
    mock_structlog.processors.StackInfoRenderer = Mock()
    mock_structlog.processors.format_exc_info = Mock()
    mock_structlog.processors.UnicodeDecoder = Mock()
    mock_structlog.processors.JSONRenderer = Mock()
    return mock_structlog


@pytest.fixture(autouse=True)
def mock_imports():
    """Stub heavy external dependencies so unit tests stay hermetic.

    This keeps ``test_main`` from starting a real uvicorn server and stops any
    test making a real HTTP request.

    IMPORTANT: never reload a project module while this fixture is active.
    ``importlib.reload`` under a mocked ``sys.modules`` permanently rebinds
    that module's imported symbols to Mocks, and those survive long after the
    patch exits - which previously left unrelated later tests constructing the
    server against a Mock ``FastMCP``.
    """
    with patch.dict(
        "sys.modules",
        {
            "fastmcp": Mock(),
            "structlog": Mock(),
            "pydantic": Mock(),
            "pydantic_settings": Mock(),
            "fastapi": Mock(),
            "uvicorn": Mock(),
            "httpx": Mock(),
            "requests": Mock(),
        },
    ):
        yield


@pytest.fixture
def mock_app():
    """Provide mock FastAPI app for testing."""
    app = Mock()
    app.routes = [
        Mock(path="/health"),
        Mock(path="/mcp"),
        Mock(path="/mcp/tools"),
        Mock(path="/mcp/resources"),
    ]
    app.router = Mock()
    return app


@pytest.fixture
def mock_client():
    """Provide mock HTTP client for testing."""
    client = Mock()
    client.get = Mock()
    client.post = Mock()
    client.put = Mock()
    client.delete = Mock()
    return client
