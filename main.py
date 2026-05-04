#!/usr/bin/env python3
"""Cursor MCP entrypoint — stdio transport."""

from mosk_rockoon_functional_agent.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
