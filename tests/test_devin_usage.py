#!/usr/bin/env python3
"""Regression tests for the devin-usage plugin layout and MCP server.

Run from the repo root:
    python3 -m unittest discover -s tests -v

Covers:
- plugin layout: no root .mcp.json project-config collision; manifest
  mcpServers declaration points at a contained .devin-plugin/mcp.json
- CLI discovery: `devin mcp get devin-usage` resolves via the plugin source
  (not a project .mcp.json) from both the repo and an unrelated directory
- MCP stdio protocol: server/discover -> -32601, initialize, silent
  notifications/initialized, tools/list, ping, no unsolicited output
- tools/call get_quota_usage with a mocked collector (no private data / no
  network): returns text content with isError=false
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")
SERVER = os.path.join(SCRIPTS, "mcp_server.py")
PLUGIN_JSON = os.path.join(REPO, ".devin-plugin", "plugin.json")

DEVIN = shutil.which("devin") or os.path.expanduser("~/.local/bin/devin")

CANNED = {
    "timestamp": "2026-10-21T02:00:00",
    "quota": {
        "planName": "TestPlan",
        "teamName": "TestTeam",
        "source": "cache",
        "weeklyRemainingPercent": 88,
        "dailyRemainingPercent": 95,
        "weeklyResetAtUnix": 1800000000,
        "dailyResetAtUnix": 1800000000,
        "acuConsumed": 12.5,
        "acuLimit": 500,
        "overageBalanceMicros": 0,
    },
    "activeSession": None,
    "today": {},
}


def rpc(method, req_id=None, params=None):
    msg = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        msg["id"] = req_id
    if params is not None:
        msg["params"] = params
    return msg


def run_server(messages, timeout=15):
    """Spawn the real stdio server, feed JSON-RPC lines, return (responses_by_id,
    raw_stdout, stderr, exit_code)."""
    proc = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = "".join(json.dumps(m) + "\n" for m in messages)
    try:
        out, err = proc.communicate(input=payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()          # test-owned subprocess only
        proc.communicate()   # drain pipes so no orphan remains
        raise
    lines = [ln for ln in out.splitlines() if ln.strip()]
    responses = {}
    for ln in lines:
        parsed = json.loads(ln)  # raises -> test failure = unsolicited output
        if parsed.get("id") is not None:
            responses[parsed["id"]] = parsed
    return responses, lines, err, proc.returncode


class TestPluginLayout(unittest.TestCase):
    def test_root_mcp_json_absent(self):
        self.assertFalse(
            os.path.exists(os.path.join(REPO, ".mcp.json")),
            "root .mcp.json must not exist: it is auto-loaded as a project "
            "config and shadows the plugin-root-aware loader",
        )

    def test_manifest_declares_contained_mcp_paths(self):
        with open(PLUGIN_JSON) as f:
            manifest = json.load(f)
        decl = manifest.get("mcpServers")
        self.assertIsInstance(decl, dict, "plugin.json must declare mcpServers")
        self.assertTrue(decl.get("exclusive"), "mcpServers.exclusive expected")
        paths = decl.get("paths")
        self.assertIsInstance(paths, list)
        self.assertTrue(paths, "mcpServers.paths must be non-empty")
        for rel in paths:
            self.assertFalse(os.path.isabs(rel), rel)
            self.assertNotIn("..", rel.split("/"), rel)
            target = os.path.realpath(os.path.join(REPO, rel))
            self.assertTrue(
                target.startswith(os.path.realpath(REPO) + os.sep),
                "%s escapes plugin root" % rel,
            )
            self.assertTrue(os.path.isfile(target), "%s missing" % rel)

    def test_mcp_declaration_contents(self):
        with open(os.path.join(REPO, ".devin-plugin", "mcp.json")) as f:
            cfg = json.load(f)
        server = cfg["mcpServers"]["devin-usage"]
        self.assertEqual(server["command"], "python3")
        self.assertEqual(
            server["args"], ["${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py"]
        )

    def test_server_and_skill_files_present(self):
        for rel in (
            "scripts/mcp_server.py",
            "scripts/usage_query.py",
            "hooks.json",
            "skills/quota/SKILL.md",
        ):
            self.assertTrue(os.path.isfile(os.path.join(REPO, rel)), rel)


class TestCliDiscovery(unittest.TestCase):
    """`devin mcp get` display shows the raw command template (the
    ${CLAUDE_PLUGIN_ROOT} token is interpolated by the plugin loader at spawn
    time). The discriminating regression signal is the Source line.

    From the repo, an intentionally noncommitted workspace override at
    .devin/mcp_config.local.json (absolute script path, git-excluded) takes
    precedence so an already-running session can use the server without a
    restart; without that file the plugin source must resolve instead. From any
    other directory the plugin source is the only valid resolution."""

    LOCAL_CFG = os.path.join(REPO, ".devin", "mcp_config.local.json")
    EXPECTED_LOCAL_ARGS = [os.path.join(SCRIPTS, "mcp_server.py")]

    def _get(self, cwd):
        if not os.path.isfile(DEVIN):
            self.skipTest("devin CLI not found")
        env = os.environ.copy()
        env.pop("ACP_BACKEND", None)  # agent shells may export it; strip for CLI
        proc = subprocess.run(
            [DEVIN, "mcp", "get", "devin-usage"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc

    def _assert_plugin_source(self, output):
        self.assertIn("devin-usage", output)
        self.assertIn("Source: plugin", output)
        self.assertNotIn(".mcp.json", output.split("Command")[0],
                         "server must not resolve via a project .mcp.json")
        src_line = [ln for ln in output.splitlines() if "Source: plugin" in ln][0]
        src_path = os.path.realpath(
            os.path.expanduser(src_line.split("Source: plugin", 1)[1].strip()))
        self.assertEqual(src_path, os.path.realpath(REPO),
                         "plugin source must resolve to this checkout")
        cmd_line = [ln for ln in output.splitlines() if "Command:" in ln][0]
        self.assertIn("scripts/mcp_server.py", cmd_line)
        self.assertNotIn("python3 /scripts/mcp_server.py", cmd_line,
                         "variable expanded to empty = broken spawn path")

    def _local_override(self):
        """Return the local devin-usage entry if .devin/mcp_config.local.json
        declares it; fail on a malformed/conflicting override."""
        if not os.path.isfile(self.LOCAL_CFG):
            return None
        with open(self.LOCAL_CFG) as f:
            cfg = json.load(f)
        entry = cfg.get("mcpServers", {}).get("devin-usage")
        self.assertIsNotNone(
            entry, "local override exists but declares no devin-usage entry"
        )
        self.assertEqual(entry.get("command"), "python3")
        self.assertEqual(
            entry.get("args"), self.EXPECTED_LOCAL_ARGS,
            "local override args must be the exact absolute script path",
        )
        return entry

    def _assert_local_source(self, output):
        self.assertIn("devin-usage", output)
        self.assertIn(".devin/mcp_config.local.json", output)
        cmd_line = [ln for ln in output.splitlines() if "Command:" in ln][0]
        self.assertIn(
            "python3 " + self.EXPECTED_LOCAL_ARGS[0], cmd_line,
            "local override must resolve to the absolute script path",
        )
        self.assertNotIn("${", cmd_line)

    def test_mcp_get_from_repo_dir(self):
        proc = self._get(REPO)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if self._local_override() is not None:
            self._assert_local_source(proc.stdout)
        else:
            self._assert_plugin_source(proc.stdout)

    def test_mcp_get_from_other_dir(self):
        with tempfile.TemporaryDirectory() as other:
            proc = self._get(other)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self._assert_plugin_source(proc.stdout)


class TestMcpProtocol(unittest.TestCase):
    def test_discover_probe_returns_32601_same_id(self):
        responses, _, err, rc = run_server([rpc("server/discover", 99)])
        self.assertEqual(err.strip(), "")
        self.assertEqual(rc, 0)
        resp = responses[99]
        self.assertEqual(resp["error"]["code"], -32601)

    def test_initialize_result(self):
        responses, _, _, _ = run_server([
            rpc("initialize", 1, {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            })
        ])
        result = responses[1]["result"]
        self.assertIn(result["protocolVersion"], mcp_server_versions())
        self.assertEqual(result["serverInfo"]["name"], "devin-usage")
        self.assertEqual(result["serverInfo"]["version"], "1.0.0")
        self.assertIn("tools", result["capabilities"])

    def test_initialized_notification_is_silent(self):
        responses, lines, _, _ = run_server([
            rpc("notifications/initialized"),
            rpc("ping", 7),
        ])
        self.assertEqual(len(lines), 1, "notification must produce no output")
        self.assertEqual(responses[7]["result"], {})

    def test_tools_list_contains_get_quota_usage(self):
        responses, _, _, _ = run_server([rpc("tools/list", 2)])
        names = [t["name"] for t in responses[2]["result"]["tools"]]
        self.assertIn("get_quota_usage", names)

    def test_ping_result(self):
        responses, _, _, _ = run_server([rpc("ping", 3)])
        self.assertEqual(responses[3]["result"], {})

    def test_full_handshake_no_unsolicited_output(self):
        msgs = [
            rpc("server/discover", 10),
            rpc("initialize", 1, {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            }),
            rpc("notifications/initialized"),
            rpc("tools/list", 2),
            rpc("ping", 3),
        ]
        responses, lines, err, rc = run_server(msgs)
        self.assertEqual(err.strip(), "", "stderr must be empty")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(responses), [1, 2, 3, 10])
        self.assertEqual(len(lines), 4)


class TestToolsCallMocked(unittest.TestCase):
    """tools/call with collect_all patched -- no quota API, no sessions.db."""

    def _call(self, arguments):
        sys.path.insert(0, SCRIPTS)
        try:
            import mcp_server  # noqa: E402 -- import inside test for path setup
            req = rpc("tools/call", 5, {
                "name": "get_quota_usage",
                "arguments": arguments,
            })
            stdin = io.StringIO(json.dumps(req) + "\n")
            stdout = io.StringIO()
            with mock.patch.object(
                mcp_server, "collect_all", return_value=CANNED
            ) as coll:
                with mock.patch("sys.stdin", stdin):
                    with mock.patch("sys.stdout", stdout):
                        mcp_server.main()
            coll.assert_called_once()
            lines = [ln for ln in stdout.getvalue().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 1)
            return json.loads(lines[0])
        finally:
            sys.path.remove(SCRIPTS)
            sys.modules.pop("mcp_server", None)
            sys.modules.pop("usage_query", None)

    def test_call_markdown(self):
        resp = self._call({"format": "markdown"})
        self.assertEqual(resp["id"], 5)
        self.assertNotIn("error", resp)
        result = resp["result"]
        self.assertFalse(result["isError"])
        content = result["content"][0]
        self.assertEqual(content["type"], "text")
        self.assertIn("88%", content["text"])  # canned weekly remaining
        self.assertIn("TestPlan", content["text"])

    def test_call_json_format(self):
        resp = self._call({"format": "json"})
        result = resp["result"]
        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload, CANNED)

    def test_call_unknown_tool_32601(self):
        sys.path.insert(0, SCRIPTS)
        try:
            import mcp_server  # noqa: E402
            req = rpc("tools/call", 6, {"name": "nope", "arguments": {}})
            stdout = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(json.dumps(req) + "\n")):
                with mock.patch("sys.stdout", stdout):
                    mcp_server.main()
            resp = json.loads(stdout.getvalue().strip())
            self.assertEqual(resp["id"], 6)
            self.assertEqual(resp["error"]["code"], -32601)
        finally:
            sys.path.remove(SCRIPTS)
            sys.modules.pop("mcp_server", None)
            sys.modules.pop("usage_query", None)


def mcp_server_versions():
    sys.path.insert(0, SCRIPTS)
    try:
        import mcp_server  # noqa: E402
        return mcp_server.SUPPORTED_VERSIONS
    finally:
        sys.path.remove(SCRIPTS)
        sys.modules.pop("mcp_server", None)
        sys.modules.pop("usage_query", None)


if __name__ == "__main__":
    unittest.main()
