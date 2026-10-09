"""MCP server 12/12 (LLM SECURITY, output side): hallucination + unsafe-answer checks."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import guard_logic as g

mcp = FastMCP("llm_output_guard")


@mcp.tool()
def verify_answer(answer: str) -> dict:
    """Check an LLM answer against the database: unknown doctors, wrong fees, diagnosis/dosage
    statements, leaked secrets. verdict is ok or block; text is the safe text to show."""
    return g.check_output(answer)


if __name__ == "__main__":
    mcp.run()
