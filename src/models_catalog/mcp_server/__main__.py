"""stdio olarak çalıştırma (MCP Inspector / lokal deneme): python -m models_catalog.mcp_server"""
from .server import mcp

if __name__ == "__main__":
    mcp.run("stdio")
