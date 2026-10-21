# Local Installation Acceptance

Date: 2026-10-21

Result: PASS for installing the current repaired working tree as a local Devin
plugin and using its namespaced skill in a fresh CLI session.

## Scope

- Devin CLI: `3000.11.92` (`7f4e64980e22`), macOS ARM64.
- Plugin: `devin-usage` `1.0.0`, including the current local MCP configuration fix.
- Authentication: an existing signed-in account; browser login was not retested.
- Installation source: a clean copy of the working tree, not a GitHub release.
- Verification was performed before publication and applies to the source contents of this change.
- This verifies installation, execution, and display, not an independent audit of
  the quota/token accounting formulas or all offline/error conditions.

## Isolation

The test used `/tmp/devinusage-cleanroom-1QvDcd/` with:

- A separate `HOME` and separate XDG configuration/data/state directories.
- A plugin checkout named `checkout with spaces`.
- An unrelated `workspace` directory for the actual skill invocation.
- No root `.mcp.json`, workspace `.devin` overrides, or user MCP configuration.
- No copy of the real user's global skills, configuration, or session database.

The first environment-variable-only authentication attempt failed the CLI's
plugin-management login gate. The successful run used a private, temporary
`credentials.toml` copy with mode `0600`, created exclusively for this test.
It was removed afterward; the real credentials and plugin registration were
unchanged. API-key bytes were not present in the retained sandbox artifacts.

## Acceptance Results

| Check | Evidence | Result |
| --- | --- | --- |
| Fresh local install from a path containing spaces | `step_1_install.log`, exit 0 | PASS |
| Exactly one installed plugin, version 1.0.0 | `step_2_list.log`, `sandbox_lock.json` | PASS |
| Namespaced skill, two hooks, and MCP registered | `step_3_info.log`, `step_5_skills_show.log` | PASS |
| Plugin-source discovery from unrelated workspace | `step_6a_mcp_get_workspace.log` | PASS |
| Plugin-source discovery from plugin checkout | `step_6b_mcp_get_plugincopy.log` | PASS |
| Repeated installation remains a single registration | `step_7_reinstall_idempotent.log`, `sandbox_lock.json` | PASS |
| Fresh native CLI invocation of `/devin-usage:quota` | `step_8_session.log`, exit 0 | PASS |
| Plugin-root variable resolves to the installed cache | `runtime_evidence.log` | PASS |
| MCP connects, lists tools, and calls the quota tool | `runtime_evidence.log`, exported session | PASS |
| Tool runs without an interactive permission prompt | Auto-decided Allow in runtime log | PASS |
| SessionStart injects actual account context | Exported session system message | PASS |
| UserPromptSubmit injects actual usage context | Exported session system message | PASS |
| Real API result includes all three panel sections | Exported tool response | PASS |
| Final response matches the tool's Markdown | Exact comparison, trailing newline ignored | PASS |
| Temporary credential copy removed | File absent after cleanup | PASS |

## Actual Invocation

With the isolated profile and existing credentials configured privately, the
following ran from the unrelated workspace:

```bash
devin --model gpt-6-1-sol-high \
  --permission-mode auto \
  --respect-workspace-trust false \
  --export /tmp/devinusage-cleanroom-1QvDcd/evidence/session.md \
  -p /devin-usage:quota
```

Workspace trust was bypassed only for the empty, test-owned directory. The
permission mode remained `auto`; no dangerous mode or broad tool grant was used.

The fresh session ID was `tidy-water`. Its transcript contains actual
`Current account quota status:` and `Live Devin quota & usage snapshot:`
system messages, plugin skill activation, tool discovery, and one
`get_quota_usage` call with `{"format":"markdown"}`. Its final Markdown equals
the tool response after ignoring the trailing newline only.

## Retained Evidence

All installation and runtime artifacts are under:

```text
/tmp/devinusage-cleanroom-1QvDcd/evidence/
```

`session.md` is the CLI's JSON-format conversation export despite its extension.
The runtime log is also retained under the sandbox profile:

```text
/tmp/devinusage-cleanroom-1QvDcd/home/.local/share/devin/cli/logs/devin_20261021-022225_44862.log
```

Earlier regression evidence remains under `/tmp/devinusage-fix-L9xaDR/`:
15 tests passed on Python 3.15 and Python 3.9.6 before the clean-room run.
No additional model session was needed to review these captured results.
