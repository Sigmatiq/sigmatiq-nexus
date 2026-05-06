#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import time as dt_time
from typing import Any
from urllib.parse import quote
from urllib.parse import urlparse

import redis
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    severity: str = "fail"  # fail | warn


def run_json(cmd: list[str]) -> Any:
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.PIPE)
    return json.loads(out)


def strip_bom(value: str | None) -> str:
    raw = value or ""
    return raw.lstrip("\ufeff").strip()


def is_regular_hours_et(now_utc: datetime) -> bool:
    now_et = now_utc.astimezone(ET)
    t = now_et.time()
    return now_et.weekday() < 5 and dt_time(9, 30) <= t < dt_time(16, 0)


def parse_symbols(raw: str) -> list[str]:
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def parse_stackexchange_redis_conn(value: str) -> str:
    raw = strip_bom(value)
    if "://" in raw:
        return raw
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise RuntimeError("REDIS_URL is empty")
    host_port = parts[0]
    if ":" not in host_port:
        raise RuntimeError("REDIS_URL missing host:port")
    host, port = host_port.rsplit(":", 1)
    opts: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            opts[k.strip().lower()] = v.strip()
    password = opts.get("password", "")
    ssl = opts.get("ssl", "true").lower() == "true"
    scheme = "rediss" if ssl else "redis"
    return f"{scheme}://:{quote(password)}@{host}:{port}/0"


def redis_client(redis_url: str) -> redis.Redis:
    return redis.Redis.from_url(redis_url, ssl_cert_reqs=None, decode_responses=True)


def resolve_env_value(app_name: str, resource_group: str, key: str) -> str:
    app = run_json(["az", "containerapp", "show", "-n", app_name, "-g", resource_group, "-o", "json"])
    env_items = (
        app.get("properties", {})
        .get("template", {})
        .get("containers", [{}])[0]
        .get("env", [])
    )
    for item in env_items:
        if str(item.get("name", "")).strip() != key:
            continue
        if "value" in item:
            return str(item.get("value") or "")
        if "secretRef" in item:
            secret_name = str(item.get("secretRef") or "").strip()
            if not secret_name:
                return ""
            secret = run_json(
                [
                    "az",
                    "containerapp",
                    "secret",
                    "show",
                    "-n",
                    app_name,
                    "-g",
                    resource_group,
                    "--secret-name",
                    secret_name,
                    "-o",
                    "json",
                ]
            )
            return strip_bom(str(secret.get("value", "")))
        return ""
    return ""


def decode_json_blob(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def freshness_check(payload: dict[str, Any] | None, max_age_minutes: int) -> tuple[bool, str]:
    if not payload:
        return False, "missing payload"
    ts = parse_iso_datetime(str(payload.get("timestamp") or payload.get("tsUtc") or payload.get("ts_utc") or ""))
    if ts is None:
        return False, "missing timestamp"
    age_minutes = (datetime.now(tz=ts.tzinfo or ZoneInfo("UTC")) - ts).total_seconds() / 60.0
    return age_minutes <= max_age_minutes, f"age_minutes={age_minutes:.1f} max_age_minutes={max_age_minutes}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-deploy smoke for Nexus Redis publish and overlay freshness.")
    parser.add_argument("--resource-group", default="rg-sig-production")
    parser.add_argument("--app-name", default="sigmatiq-nexus-ca")
    parser.add_argument("--symbols", default="SPY,QQQ,IWM")
    parser.add_argument("--max-age-minutes", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    checks: list[CheckResult] = []
    details: dict[str, Any] = {}

    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    regular_hours = is_regular_hours_et(now_utc)
    details["marketPhase"] = "regular_hours" if regular_hours else "outside_regular_hours"
    details["timestampEt"] = now_utc.astimezone(ET).isoformat()

    try:
        app = run_json(["az", "containerapp", "show", "-n", args.app_name, "-g", args.resource_group, "-o", "json"])
    except Exception as exc:
        print(json.dumps({"disposition": "blocked", "error": f"Failed to read container app: {exc}"}, indent=2))
        return 1

    status = app.get("properties", {}).get("runningStatus")
    checks.append(CheckResult("app_running", status == "Running", f"runningStatus={status}"))

    redis_url_raw = resolve_env_value(args.app_name, args.resource_group, "REDIS_URL")
    checks.append(CheckResult("redis_url_present", bool(redis_url_raw), "REDIS_URL present"))
    if not redis_url_raw:
        failed = [c for c in checks if not c.ok and c.severity == "fail"]
        summary = {
            "disposition": "blocked",
            "failedCount": len(failed),
            "warningCount": 0,
            "checks": [asdict(c) for c in checks],
            "details": details,
        }
        print(json.dumps(summary, indent=2, default=str) if args.json else "blocked")
        return 1

    redis_url = parse_stackexchange_redis_conn(redis_url_raw)
    details["redisHost"] = urlparse(redis_url).hostname

    try:
        r = redis_client(redis_url)
        details["redisPing"] = bool(r.ping())
        checks.append(CheckResult("redis_ping", bool(r.ping()), "PING successful"))

        overlay: dict[str, Any] = {}
        for sym in parse_symbols(args.symbols):
            payload = decode_json_blob(r.get(f"nexus_live_overlay:{sym}"))
            overlay[sym] = payload
            checks.append(CheckResult(f"overlay_present_{sym}", payload is not None, f"nexus_live_overlay:{sym} present"))
            if payload:
                checks.append(CheckResult(f"overlay_symbol_{sym}", str(payload.get("symbol", "")).upper() == sym, f"symbol={payload.get('symbol')}"))
                checks.append(CheckResult(f"overlay_strategy_{sym}", payload.get("strategy") == "open30_sniper_v1", f"strategy={payload.get('strategy')}"))
                checks.append(CheckResult(f"overlay_stage_{sym}", int(payload.get("stage") or 0) == 2, f"stage={payload.get('stage')}"))
                fresh, detail = freshness_check(payload, args.max_age_minutes)
                checks.append(CheckResult(f"overlay_fresh_{sym}", fresh, detail))

        details["overlay"] = overlay
        if regular_hours:
            any_overlay = any(payload is not None for payload in overlay.values())
            checks.append(CheckResult("regular_hours_overlay_present", any_overlay, "At least one overlay key present during regular hours"))
        else:
            checks.append(
                CheckResult(
                    "overlay_outside_regular_hours",
                    True,
                    "Skipped strict overlay enforcement outside ET regular hours; deferred to scheduled market-open smoke.",
                    severity="warn",
                )
            )
    except Exception as exc:
        checks.append(CheckResult("redis_validation", False, f"Redis validation failed: {exc}"))

    failed = [c for c in checks if not c.ok and c.severity == "fail"]
    warnings = [c for c in checks if (not c.ok and c.severity == "warn") or (c.ok and c.severity == "warn")]
    disposition = "blocked" if failed else ("healthy_with_warnings" if warnings else "healthy")

    summary = {
        "disposition": disposition,
        "failedCount": len(failed),
        "warningCount": len(warnings),
        "marketPhase": details.get("marketPhase"),
        "checks": [asdict(c) for c in checks],
        "details": details,
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"disposition={disposition} failed={len(failed)} warnings={len(warnings)} phase={details.get('marketPhase')}")
        for c in checks:
            state = "OK" if c.ok else ("WARN" if c.severity == "warn" else "FAIL")
            print(f"[{state}] {c.name} :: {c.detail}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
