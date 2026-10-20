#!/usr/bin/env python3
"""
Core quota & session token usage collector for Devin Desktop / Devin CLI.
Reads live quota from SeatManagementService/GetUserStatus (with local cache fallback)
and local session/token metrics from ~/.local/share/devin/cli/sessions.db.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import platform
import re
import sqlite3
import time
import urllib.request
from typing import Any

HOME = os.path.expanduser("~")


def _candidate_credentials_paths() -> list[str]:
    paths = [
        os.path.join(HOME, ".local", "share", "devin", "credentials.toml"),
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, "devin", "credentials.toml"))
    return paths


def _candidate_state_db_paths() -> list[str]:
    sys_name = platform.system()
    paths = []
    if sys_name == "Darwin":
        for app in ("Devin", "Windsurf"):
            paths.append(
                os.path.join(
                    HOME,
                    "Library",
                    "Application Support",
                    app,
                    "User",
                    "globalStorage",
                    "state.vscdb",
                )
            )
    elif sys_name == "Windows":
        appdata = os.environ.get("APPDATA") or os.path.join(HOME, "AppData", "Roaming")
        for app in ("Devin", "Windsurf"):
            paths.append(
                os.path.join(appdata, app, "User", "globalStorage", "state.vscdb")
            )
    else:
        for app in ("Devin", "Windsurf"):
            paths.append(
                os.path.join(
                    HOME, ".config", app, "User", "globalStorage", "state.vscdb"
                )
            )
    return paths


def _candidate_sessions_db_paths() -> list[str]:
    paths = [
        os.path.join(HOME, ".local", "share", "devin", "cli", "sessions.db"),
    ]
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        paths.append(os.path.join(localappdata, "devin", "cli", "sessions.db"))
    return paths


def _first_existing(paths: list[str]) -> str | None:
    for p in paths:
        if os.path.exists(p):
            return p
    return None


def fmt_tokens(n: int | float | None) -> str:
    if not n or n <= 0:
        return "0"
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(int(n))


def fmt_countdown(unix_sec: int | float | None) -> str:
    if not unix_sec:
        return "-"
    diff = int(unix_sec) - int(time.time())
    if diff <= 0:
        return "即将重置"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    mins = (diff % 3600) // 60
    if days > 0:
        return f"{days}天{hours}小时"
    if hours > 0:
        return f"{hours}小时{mins}分"
    return f"{mins}分钟"


def fmt_timestamp(unix_sec: int | float | None) -> str:
    if not unix_sec:
        return "-"
    dt = datetime.datetime.fromtimestamp(int(unix_sec))
    return dt.strftime("%Y-%m-%d %H:%M")


def progress_bar(percent_remaining: int | float, width: int = 20) -> str:
    p = max(0.0, min(100.0, float(percent_remaining or 0)))
    filled = round((p / 100.0) * width)
    return "█" * filled + "░" * max(0, width - filled)


def load_auth_and_cache() -> tuple[str | None, str, dict[str, Any] | None]:
    api_key = os.environ.get("WINDSURF_API_KEY")
    api_server = os.environ.get("WINDSURF_API_SERVER_URL") or "https://server.codeium.com"
    cached_plan = None

    cred_path = _first_existing(_candidate_credentials_paths())
    if cred_path:
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                raw = f.read()
            if not api_key:
                m_key = re.search(r'windsurf_api_key\s*=\s*"([^"]+)"', raw)
                if m_key:
                    api_key = m_key.group(1).strip()
            m_url = re.search(r'api_server_url\s*=\s*"([^"]+)"', raw)
            if m_url:
                api_server = m_url.group(1).strip()
        except Exception:
            pass

    state_db = _first_existing(_candidate_state_db_paths())
    if state_db:
        try:
            conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=2.0)
            c = conn.cursor()
            if not api_key:
                c.execute(
                    "SELECT value FROM ItemTable WHERE key = 'windsurfAuthStatus' LIMIT 1;"
                )
                row = c.fetchone()
                if row:
                    api_key = json.loads(row[0]).get("apiKey")
            c.execute(
                "SELECT value FROM ItemTable WHERE key LIKE 'windsurf.reactSettings.cachedPlanInfoData:%' LIMIT 1;"
            )
            row_cache = c.fetchone()
            if row_cache:
                cached_plan = json.loads(row_cache[0])
            conn.close()
        except Exception:
            pass

    return api_key, api_server.rstrip("/"), cached_plan


def fetch_quota() -> dict[str, Any] | None:
    api_key, api_server, cached_plan = load_auth_and_cache()
    if api_key:
        try:
            req = urllib.request.Request(
                f"{api_server}/exa.seat_management_pb.SeatManagementService/GetUserStatus",
                data=json.dumps(
                    {
                        "metadata": {
                            "apiKey": api_key,
                            "ideName": "windsurf",
                            "ideVersion": "3.10.67",
                            "extensionName": "windsurf",
                            "extensionVersion": "3.10.67",
                            "locale": "zh-cn",
                        }
                    }
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Connect-Protocol-Version": "1",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                us = data.get("userStatus") or {}
                ps = us.get("planStatus") or {}
                pi = ps.get("planInfo") or {}
                if ps:
                    return {
                        "source": "live",
                        "planName": pi.get("planName") or "Max",
                        "teamsTier": pi.get("teamsTier") or "",
                        "teamName": (pi.get("devinInfo") or {}).get(
                            "accountDisplayName"
                        )
                        or "",
                        "billingStrategy": pi.get("billingStrategy")
                        or "BILLING_STRATEGY_QUOTA",
                        "hideDailyQuota": bool(pi.get("hideDailyQuota")),
                        "hideWeeklyQuota": bool(pi.get("hideWeeklyQuota")),
                        "dailyRemainingPercent": ps.get(
                            "dailyQuotaRemainingPercent", 100
                        ),
                        "weeklyRemainingPercent": ps.get(
                            "weeklyQuotaRemainingPercent", 100
                        ),
                        "dailyResetAtUnix": int(ps.get("dailyQuotaResetAtUnix") or 0),
                        "weeklyResetAtUnix": int(
                            ps.get("weeklyQuotaResetAtUnix") or 0
                        ),
                        "overageBalanceMicros": int(
                            ps.get("overageBalanceMicros") or 0
                        ),
                        "acuConsumed": ps.get("acuConsumed"),
                        "acuLimit": ps.get("acuLimit"),
                        "planStart": ps.get("planStart"),
                        "planEnd": ps.get("planEnd"),
                    }
        except Exception:
            pass

    if cached_plan:
        team_raw = cached_plan.get("accountIdentityText") or ""
        if " - " in team_raw:
            team_raw = team_raw.split(" - ", 1)[1]
        return {
            "source": "cache",
            "planName": cached_plan.get("planName") or "Max",
            "teamsTier": str(cached_plan.get("teamsTier") or ""),
            "teamName": team_raw,
            "billingStrategy": cached_plan.get("billingStrategy") or "quota",
            "hideDailyQuota": bool(cached_plan.get("hideDailyQuota")),
            "hideWeeklyQuota": bool(cached_plan.get("hideWeeklyQuota")),
            "dailyRemainingPercent": cached_plan.get("dailyRemainingPercent", 100),
            "weeklyRemainingPercent": cached_plan.get("weeklyRemainingPercent", 100),
            "dailyResetAtUnix": int(cached_plan.get("dailyResetAtUnix") or 0),
            "weeklyResetAtUnix": int(cached_plan.get("weeklyResetAtUnix") or 0),
            "overageBalanceMicros": int(cached_plan.get("overageBalanceMicros") or 0),
            "acuConsumed": cached_plan.get("acuConsumed"),
            "acuLimit": cached_plan.get("acuLimit"),
            "planStart": cached_plan.get("startTimestamp"),
            "planEnd": cached_plan.get("endTimestamp"),
        }
    return None


def fetch_sessions_stats(cwd: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"activeSession": None, "today": None}
    sessions_db = _first_existing(_candidate_sessions_db_paths())
    if not sessions_db:
        return result

    try:
        conn = sqlite3.connect(f"file:{sessions_db}?mode=ro", uri=True, timeout=2.5)
        c = conn.cursor()

        active_row = None
        if cwd:
            c.execute(
                "SELECT id, working_directory, model, agent_mode, created_at, last_activity_at, title "
                "FROM sessions WHERE hidden = 0 AND working_directory = ? ORDER BY last_activity_at DESC LIMIT 1;",
                (cwd,),
            )
            active_row = c.fetchone()
        if not active_row:
            c.execute(
                "SELECT id, working_directory, model, agent_mode, created_at, last_activity_at, title "
                "FROM sessions WHERE hidden = 0 ORDER BY last_activity_at DESC LIMIT 1;"
            )
            active_row = c.fetchone()

        if active_row:
            sid, wd, model, mode, _created_at, _last_act, title = active_row
            c.execute(
                "SELECT metadata, CASE WHEN substr(chat_message, 1, 90) LIKE ? "
                "THEN json_extract(chat_message, ?) ELSE NULL END "
                "FROM message_nodes WHERE session_id = ? ORDER BY row_id DESC LIMIT 300;",
                ('%"role":"assistant"%', "$.metadata", sid),
            )
            seen_reqs: set[str] = set()
            in_tok = 0
            out_tok = 0
            cache_tok = 0
            turns = 0
            ctx_tokens = 0
            last_tps = None
            last_model = None
            for nmeta_str, msg_meta_str in c.fetchall():
                try:
                    if not ctx_tokens and nmeta_str:
                        nm = json.loads(nmeta_str)
                        if nm and nm.get("num_tokens_preceding"):
                            ctx_tokens = nm.get("num_tokens_preceding")
                    if not msg_meta_str:
                        continue
                    mm = json.loads(msg_meta_str)
                    req_id = mm.get("request_id")
                    if not req_id or req_id in seen_reqs:
                        continue
                    seen_reqs.add(req_id)
                    turns += 1
                    if not last_model and mm.get("generation_model"):
                        last_model = mm.get("generation_model")
                    metrics = mm.get("metrics") or {}
                    it = metrics.get("input_tokens") or 0
                    ot = metrics.get("output_tokens") or 0
                    ct = metrics.get("cache_read_tokens") or 0
                    in_tok += it
                    out_tok += ot
                    cache_tok += ct
                    if not ctx_tokens and (ct + it > 0):
                        ctx_tokens = ct + it + ot
                    if last_tps is None and metrics.get("tokens_per_sec"):
                        last_tps = metrics.get("tokens_per_sec")
                except Exception:
                    pass
            result["activeSession"] = {
                "id": sid,
                "title": title or sid,
                "workingDirectory": wd,
                "model": last_model or model,
                "mode": mode,
                "turns": turns,
                "contextTokens": ctx_tokens,
                "inputTokens": in_tok,
                "outputTokens": out_tok,
                "cacheReadTokens": cache_tok,
                "tokensPerSec": round(last_tps, 1) if last_tps else None,
            }

        # Today's cumulative stats across all sessions active since local midnight
        lt = time.localtime()
        midnight = int(
            time.mktime(
                (
                    lt.tm_year,
                    lt.tm_mon,
                    lt.tm_mday,
                    0,
                    0,
                    0,
                    lt.tm_wday,
                    lt.tm_yday,
                    lt.tm_isdst,
                )
            )
        )
        midnight_iso = datetime.datetime.fromtimestamp(
            midnight, tz=datetime.timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        c.execute("SELECT id FROM sessions WHERE last_activity_at >= ?;", (midnight,))
        active_sids = [r[0] for r in c.fetchall()]

        seen_today: set[str] = set()
        today_in = 0
        today_out = 0
        today_cache = 0
        today_turns = 0
        today_sessions: set[str] = set()
        by_model: dict[str, dict[str, int]] = {}

        for sid in active_sids:
            c.execute(
                "SELECT CASE WHEN substr(chat_message, 1, 90) LIKE ? "
                "THEN json_extract(chat_message, ?) ELSE NULL END "
                "FROM message_nodes WHERE session_id = ? ORDER BY row_id DESC;",
                ('%"role":"assistant"%', "$.metadata", sid),
            )
            for (meta_str,) in c:
                if not meta_str:
                    continue
                try:
                    mm = json.loads(meta_str)
                    msg_ts = (
                        mm.get("created_at") or mm.get("started_generation_at") or ""
                    )
                    if msg_ts and msg_ts < midnight_iso:
                        break
                    req_id = mm.get("request_id")
                    if not req_id or req_id in seen_today:
                        continue
                    seen_today.add(req_id)
                    today_sessions.add(sid)
                    today_turns += 1
                    mname = mm.get("generation_model") or "unknown"
                    metrics = mm.get("metrics") or {}
                    it = metrics.get("input_tokens") or 0
                    ot = metrics.get("output_tokens") or 0
                    ct = metrics.get("cache_read_tokens") or 0
                    today_in += it
                    today_out += ot
                    today_cache += ct
                    bm = by_model.setdefault(
                        mname, {"turns": 0, "input": 0, "output": 0, "cache": 0}
                    )
                    bm["turns"] += 1
                    bm["input"] += it
                    bm["output"] += ot
                    bm["cache"] += ct
                except Exception:
                    pass

        result["today"] = {
            "sessionsCount": len(today_sessions),
            "turns": today_turns,
            "inputTokens": today_in,
            "outputTokens": today_out,
            "cacheReadTokens": today_cache,
            "byModel": by_model,
        }
        conn.close()
    except Exception:
        pass

    return result


def collect_all(cwd: str = "") -> dict[str, Any]:
    quota = fetch_quota()
    stats = fetch_sessions_stats(cwd)
    return {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "quota": quota,
        "activeSession": stats.get("activeSession"),
        "today": stats.get("today"),
    }


def render_brief(data: dict[str, Any]) -> str:
    q = data.get("quota")
    s = data.get("activeSession")
    parts = []
    if q:
        w_rem = q.get("weeklyRemainingPercent", 100)
        w_used = 100 - w_rem
        w_reset = fmt_countdown(q.get("weeklyResetAtUnix"))
        parts.append(
            f"[Devin {q.get('planName', 'Max')}] 周额度剩余 {w_rem}% (已用 {w_used}%, 重置倒计时: {w_reset})"
        )
    if s and s.get("contextTokens"):
        parts.append(
            f"当前会话上下文: {fmt_tokens(s['contextTokens'])} tokens (模型: {s.get('model')})"
        )
    return " | ".join(parts) if parts else "Devin 配额状态正常"


def render_markdown(data: dict[str, Any]) -> str:
    lines = ["## 📊 Devin 账号额度与会话消耗面板", ""]
    q = data.get("quota")
    if q:
        w_rem = max(0, min(100, int(q.get("weeklyRemainingPercent", 100))))
        w_used = 100 - w_rem
        w_bar = progress_bar(w_rem, 20)
        w_reset = fmt_countdown(q.get("weeklyResetAtUnix"))
        w_reset_dt = fmt_timestamp(q.get("weeklyResetAtUnix"))
        status_tag = (
            "🟢 充足"
            if w_rem > 20
            else ("🟡 偏低预警" if w_rem > 5 else "🔴 即将耗尽")
        )
        src_label = (
            "实时接口 (SeatManagementService)"
            if q.get("source") == "live"
            else "本地缓存"
        )

        lines.append(
            f"### 1. 账号配额 ({q.get('planName', 'Max')} · {q.get('teamName') or 'Personal'})"
        )
        lines.append("")
        lines.append("| 指标 | 状态 / 进度 | 详情 |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(
            f"| **周额度 (Weekly Quota)** | `{w_bar}` **剩余 {w_rem}%** | 已用 **{w_used}%** · {status_tag} |"
        )
        lines.append(f"| **周额度重置时间** | **{w_reset}** | `{w_reset_dt}` |")
        if not q.get("hideDailyQuota"):
            d_rem = max(0, min(100, int(q.get("dailyRemainingPercent", 100))))
            d_used = 100 - d_rem
            d_bar = progress_bar(d_rem, 20)
            d_reset = fmt_countdown(q.get("dailyResetAtUnix"))
            lines.append(
                f"| **日额度 (Daily Quota)** | `{d_bar}` **剩余 {d_rem}%** | 已用 **{d_used}%** · 重置: {d_reset} |"
            )
        if q.get("acuConsumed") is not None:
            lines.append(
                f"| **ACU 消耗** | `{q['acuConsumed']}` | 上限: `{q.get('acuLimit') or '-'}` |"
            )
        if q.get("overageBalanceMicros", 0) > 0:
            lines.append(
                f"| **额外充值余额** | `${q['overageBalanceMicros'] / 1_000_000:.2f}` | Extra Usage Balance |"
            )
        lines.append(f"| **数据来源** | `{src_label}` | 更新于 `{data['timestamp']}` |")
        lines.append("")
    else:
        lines.append("> ⚠️ 未能读取到账号配额信息，请确认已登录 Devin。")
        lines.append("")

    s = data.get("activeSession")
    if s:
        lines.append(f"### 2. 当前活跃会话 (`{s['title']}`)")
        lines.append("")
        lines.append(
            f"- **会话 ID**: `{s['id']}` · **当前模型**: `{s['model']}` · **轮数**: `{s['turns']} 轮`"
        )
        lines.append(
            f"- **当前上下文窗口 (Context Window)**: `{fmt_tokens(s['contextTokens'])} tokens`"
            + (
                f" · **生成速度**: `{s['tokensPerSec']} tok/s`"
                if s.get("tokensPerSec")
                else ""
            )
        )
        lines.append(
            f"- **本会话累计 Token**: 新输入 `{fmt_tokens(s['inputTokens'])}` · 输出 `{fmt_tokens(s['outputTokens'])}` · 缓存读取 `{fmt_tokens(s['cacheReadTokens'])}`"
        )
        lines.append("")

    t = data.get("today")
    if t and t.get("turns", 0) > 0:
        lines.append(
            f"### 3. 今日累计 Token 统计 (活跃会话 `{t['sessionsCount']}` 个 · 共 `{t['turns']}` 轮请求)"
        )
        lines.append("")
        lines.append("| 模型 | 请求轮数 | 新输入 Tokens | 输出 Tokens | 缓存命中 Tokens |")
        lines.append("| :--- | :---: | :---: | :---: | :---: |")
        for mname, mstat in sorted(
            t.get("byModel", {}).items(), key=lambda x: x[1]["turns"], reverse=True
        ):
            lines.append(
                f"| `{mname}` | {mstat['turns']} | `{fmt_tokens(mstat['input'])}` | `{fmt_tokens(mstat['output'])}` | `{fmt_tokens(mstat['cache'])}` |"
            )
        lines.append(
            f"| **今日合计** | **{t['turns']}** | **`{fmt_tokens(t['inputTokens'])}`** | **`{fmt_tokens(t['outputTokens'])}`** | **`{fmt_tokens(t['cacheReadTokens'])}`** |"
        )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Devin Quota & Usage Query")
    parser.add_argument(
        "--format",
        choices=["markdown", "brief", "json"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument("--cwd", default="", help="Workspace directory")
    args = parser.parse_args()

    data = collect_all(args.cwd or os.getcwd())
    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.format == "brief":
        print(render_brief(data))
    else:
        print(render_markdown(data))


if __name__ == "__main__":
    main()
