#!/usr/bin/env python3
"""
Standard JSON-RPC 2.0 stdio MCP server for the devin-usage plugin.
Exposes tool `get_quota_usage` to fetch live Devin account quota and local session token usage.
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from usage_query import collect_all, render_markdown  # noqa: E402

SUPPORTED_VERSIONS = {
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
}

TOOLS = [
    {
        "name": "get_quota_usage",
        "description": "获取当前 Devin 账号的实时周/日额度百分比、重置倒计时、当前会话上下文窗口大小以及今日各模型的 Token 消耗统计面板。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "default": "markdown",
                    "description": "返回格式：markdown 表格面板或原始 json 数据",
                }
            },
        },
    }
]


def send_response(msg: dict):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_request(req: dict):
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    # Notifications have no id and expect no response
    if req_id is None:
        return

    if method == "initialize":
        client_ver = params.get("protocolVersion", "2024-11-05")
        negotiated = client_ver if client_ver in SUPPORTED_VERSIONS else "2024-11-05"
        send_response(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {
                        "name": "devin-usage",
                        "version": "1.0.0",
                    },
                },
            }
        )
    elif method == "ping":
        send_response({"jsonrpc": "2.0", "id": req_id, "result": {}})
    elif method == "tools/list":
        send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "prompts/list":
        send_response({"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}})
    elif method == "resources/list":
        send_response({"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}})
    elif method == "resources/templates/list":
        send_response(
            {"jsonrpc": "2.0", "id": req_id, "result": {"resourceTemplates": []}}
        )
    elif method == "tools/call":
        tname = params.get("name")
        targs = params.get("arguments") or {}
        if tname == "get_quota_usage":
            data = collect_all(os.getcwd())
            fmt = targs.get("format", "markdown")
            text = (
                json.dumps(data, ensure_ascii=False, indent=2)
                if fmt == "json"
                else render_markdown(data)
            )
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    },
                }
            )
        else:
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tname}"},
                }
            )
    else:
        # Must return -32601 Method not found (e.g. for server/discover probe)
        # so the MCP client falls back to standard initialize handshake.
        send_response(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }
        )


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            handle_request(req)
        except Exception as e:
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
            )


if __name__ == "__main__":
    main()
