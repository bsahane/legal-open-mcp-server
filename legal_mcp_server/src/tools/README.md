# MCP Tools Directory

All MCP server capabilities are implemented as **tools** for maximum compatibility with AI agents.

## 🔧 **Tool Development Guidelines**

### **Required Tool Documentation Format**

**CRITICAL**: All tools MUST use this structured format for agent compatibility:

```python
def your_tool_function(
    input_param: str,
    optional_param: str = "default"
) -> Dict[str, Any]:
    """
    TOOL_NAME=your_tool_function
    DISPLAY_NAME=Human-Readable Tool Name
    USECASE=When/why to use this tool (specific scenarios)
    INSTRUCTIONS=Step-by-step usage guide for agents
    INPUT_DESCRIPTION=Expected data format with examples
    OUTPUT_DESCRIPTION=What format you'll receive back
    EXAMPLES=your_tool_function("example_input", "optional_value")
    PREREQUISITES=What to do first (workflow sequence)
    RELATED_TOOLS=Other tools to use with this one

    Traditional docstring for developers goes here...
    """
    try:
        # Input validation
        if not input_param:
            raise ValueError("input_param is required")

        # Your business logic here
        result = process_input(input_param, optional_param)

        return {
            "status": "success",
            "operation": "your_operation",
            "result": result,
            "message": "Operation completed successfully"
        }

    except Exception as e:
        return {
            "status": "error",
            "operation": "your_operation",
            "error": str(e),
            "message": "Operation failed"
        }
```

### **Tool Registration**

Each tool module exports a `TOOLS` list. Registration is handled by the `TOOL_GROUPS` dict in `../mcp.py` — add a new group there if creating a new module, or append to an existing module's `TOOLS` list.

Every tool function also needs an entry in `../tool_annotations.py` with `title`, `readOnlyHint`, and `destructiveHint` — a missing entry logs a warning at startup.

```python
# In your tool module (e.g. legal_mcp_server/src/tools/your_tools.py):
TOOLS = [your_tool_function, another_tool_function]

# In legal_mcp_server/src/mcp.py, add the group loader:
def _your_tools() -> List[Callable[..., Any]]:
    from legal_mcp_server.src.tools import your_tools
    return your_tools.TOOLS

TOOL_GROUPS["your"] = _your_tools

# In legal_mcp_server/src/tool_annotations.py, add metadata:
"your_tool_function": {
    "title": "Your Tool",
    "readOnlyHint": True,
    "destructiveHint": False,
},
```

## 📋 **Current Tools**

- `research_tools.py` - Case-law search, citation verification, judgment retrieval
- `statute_tools.py` - Bare-Act lookup and criminal-code concordance (IPC↔BNS, CrPC↔BNSS, Evidence↔BSA)
- `deadline_tools.py` - Limitation period computation and deadline tracking
- `matter_tools.py` - Matter management, hearing tracking, chronology
- `document_tools.py` - Document ingest, search, and review
- `drafting_tools.py` - Legal document drafting from templates
- `court_tools.py` - Court status, directory, and jurisdiction lookup

## ✅ **Best Practices**

1. **Consistent Returns**: Always return `Dict[str, Any]` with `status` field
2. **Error Handling**: Wrap in try/catch, return structured errors
3. **Input Validation**: Validate all inputs before processing
4. **Logging**: Use `from legal_mcp_server.utils.pylogger import get_python_logger`
5. **Testing**: Add tests in `../../tests/` (one test file per tool module)

## 🎯 **Agent-Friendly Tips**

- Use **clear, action-oriented names** (`generate_report` not `report_generator`)
- Include **concrete examples** in EXAMPLES field
- Specify **prerequisites** for workflow guidance
- List **related tools** to help agents chain operations
- Keep **error messages** descriptive but concise
