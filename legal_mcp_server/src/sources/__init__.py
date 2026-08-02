"""External data source adapters for the Legal MCP Server.

Modules here perform I/O against outside services and know nothing about MCP.
Each returns plain dataclasses or dictionaries so that tool modules stay thin
and the sources stay independently testable with a mocked transport.
"""
