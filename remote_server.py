import random
from fastmcp import FastMCP

# create a FastMCP server instance
mcp = FastMCP(name='Demo Sever')

@mcp.tool
def roll_dice(n_dice:int = 1) -> list[int]:
    """Roll n number of 6 faced dice and return the result"""
    return [random.randint(1,6) for _ in range(n_dice)]

@mcp.tool
def add_numbers(a: float, b: float) -> float:
    """Addd two numbers together"""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
    
# npx @modelcontextprotocol/inspector uv run your_server.py
# fastmcp run main.py --transport http --host 0.0.0.0 --port 8000
# uv run main.py