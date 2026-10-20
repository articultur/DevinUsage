#!/usr/bin/env python3
"""
Lifecycle hook runner for the devin-usage plugin.
- On SessionStart: injects a concise 1-line summary of current Devin quota & reset time.
- On UserPromptSubmit: if weekly remaining quota <= 20%, injects a low-quota warning;
  or if the user asks about quota/usage ("额度", "用量", "quota"), injects the full live snapshot.
"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from usage_query import collect_all, render_brief, render_markdown  # noqa: E402


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "session-start"
    stdin_data = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read().strip()
            if raw:
                stdin_data = json.loads(raw)
    except Exception:
        pass

    cwd = os.environ.get("DEVIN_PROJECT_DIR") or os.getcwd()
    try:
        data = collect_all(cwd)
    except Exception:
        sys.exit(0)

    if mode == "session-start":
        brief = render_brief(data)
        out = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"Current account quota status: {brief}",
            }
        }
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(0)

    if mode == "prompt-submit":
        prompt = (stdin_data.get("prompt") or "").lower()
        keywords = ["额度", "配额", "余量", "剩余多少", "quota", "usage", "token消耗"]
        if any(k in prompt for k in keywords):
            md = render_markdown(data)
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"Live Devin quota & usage snapshot:\n\n{md}",
                }
            }
            print(json.dumps(out, ensure_ascii=False))
            sys.exit(0)

        q = data.get("quota") or {}
        w_rem = q.get("weeklyRemainingPercent", 100)
        if w_rem <= 20:
            brief = render_brief(data)
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"⚠️ Low quota alert: {brief}",
                }
            }
            print(json.dumps(out, ensure_ascii=False))
        sys.exit(0)


if __name__ == "__main__":
    main()
