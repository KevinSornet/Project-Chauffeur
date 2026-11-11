"""Pull insights from Meta into the local SQLite cache.

CLI:  python -m chauffeur.sync --days 30
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import LIVE_DB, Settings, load_settings
from .meta_api import MetaAPIError, MetaClient, ProgressFn, normalize_row
from .store import connect, log_sync, upsert_rows


@dataclass
class SyncResult:
    account_id: str
    rows: int
    ok: bool
    message: str = ""


def resolve_accounts(client: MetaClient, settings: Settings) -> list[str]:
    if settings.account_ids:
        return settings.account_ids
    return [f"act_{a['account_id']}" for a in client.list_ad_accounts()]


def run_sync(
    days: int = 30,
    settings: Settings | None = None,
    db_path: Path = LIVE_DB,
    progress: ProgressFn | None = None,
) -> list[SyncResult]:
    """Re-pull the last `days` days (Meta revises recent numbers, so overlap is intentional)."""
    settings = settings or load_settings()
    if not settings.has_token:
        raise MetaAPIError("META_ACCESS_TOKEN is not set. Add it to .env (see .env.example).")
    say = progress or (lambda _m: None)
    client = MetaClient(settings.access_token, settings.api_version)
    until = date.today()
    since = until - timedelta(days=days - 1)

    accounts = resolve_accounts(client, settings)
    if not accounts:
        raise MetaAPIError("No ad accounts found for this token. Set META_AD_ACCOUNT_IDS in .env.")

    results: list[SyncResult] = []
    conn = connect(db_path)
    try:
        for i, acct in enumerate(accounts, 1):
            say(f"[{i}/{len(accounts)}] {acct}: fetching {since} → {until}")
            try:
                rows = [normalize_row(r) for r in client.ad_insights(acct, since, until)]
                n = upsert_rows(conn, rows)
                log_sync(conn, acct, since.isoformat(), until.isoformat(), n, "ok")
                results.append(SyncResult(acct, n, True))
                say(f"[{i}/{len(accounts)}] {acct}: {n} rows saved")
            except MetaAPIError as e:
                log_sync(conn, acct, since.isoformat(), until.isoformat(), 0, "error", str(e))
                results.append(SyncResult(acct, 0, False, str(e)))
                say(f"[{i}/{len(accounts)}] {acct}: ERROR {e}")
                if e.code == 190:  # bad token: no point trying other accounts
                    break
    finally:
        conn.close()
    return results


def main() -> None:
    p = argparse.ArgumentParser(description="Sync Facebook boost insights into the local cache.")
    p.add_argument("--days", type=int, default=30, help="How many days back to (re)fetch (default 30).")
    args = p.parse_args()
    results = run_sync(args.days, progress=print)
    failed = [r for r in results if not r.ok]
    print(f"Done: {sum(r.rows for r in results)} rows from {len(results) - len(failed)} account(s), {len(failed)} failed.")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
