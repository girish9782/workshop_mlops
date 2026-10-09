"""MCP server 11/12 (LLM SECURITY, input side): prompt injection, privilege escalation,
PII redaction and token budget. The agent also calls the same logic in-process before every LLM call."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import guard_logic as g

mcp = FastMCP("llm_input_guard")


@mcp.tool()
def check_user_message(text: str, role: str = "patient", max_tokens: int = 600) -> dict:
    """Verdict allow/redact/block for a message BEFORE it reaches the LLM (injection, escalation, PII, length)."""
    return g.check_input(text, role, max_tokens)


@mcp.tool()
def count_tokens(text: str) -> dict:
    """Rough token estimate (~4 chars/token) for budgeting."""
    return {"estimated_tokens": g.estimate_tokens(text)}


@mcp.tool()
def scan_untrusted_data(text: str) -> dict:
    """Check text coming from the database/tools for hidden instructions (indirect injection)."""
    return {"injection_patterns": g.detect_injection(text)}


if __name__ == "__main__":
    mcp.run()
