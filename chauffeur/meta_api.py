"""Thin client for the Meta (Facebook) Marketing API insights endpoint."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Callable, Iterator

import requests

GRAPH = "https://graph.facebook.com"

INSIGHT_FIELDS = [
    "account_id", "account_name", "account_currency",
    "campaign_id", "campaign_name", "objective",
    "adset_id", "adset_name", "ad_id", "ad_name",
    "date_start", "spend", "impressions", "reach",
    "clicks", "inline_link_clicks",
    "actions", "video_thruplay_watched_actions",
]

# Error codes Meta uses for throttling; we back off and retry these.
RATE_LIMIT_CODES = {4, 17, 32, 341, 613, 80000, 80003, 80004, 80014}
MAX_RETRIES = 6
CHUNK_DAYS = 30


class MetaAPIError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class MetaClient:
    def __init__(self, access_token: str, api_version: str = "v24.0", session: requests.Session | None = None):
        self.token = access_token
        self.base = f"{GRAPH}/{api_version}"
        self.http = session or requests.Session()

    # ---- low level -------------------------------------------------------
    def _get(self, url: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        if "access_token=" not in url:
            params["access_token"] = self.token
        for attempt in range(MAX_RETRIES):
            resp = self.http.get(url, params=params, timeout=120)
            try:
                body = resp.json()
            except ValueError:
                body = {}
            err = body.get("error")
            if resp.ok and not err:
                return body
            code = (err or {}).get("code")
            msg = (err or {}).get("message") or resp.text[:300]
            if code in RATE_LIMIT_CODES or resp.status_code >= 500:
                time.sleep(min(60, 2 ** attempt * 2))
                continue
            if code == 190:
                raise MetaAPIError("Access token is invalid or expired. Generate a new one and update .env.", code)
            raise MetaAPIError(f"Meta API error {code}: {msg}", code)
        raise MetaAPIError("Meta API kept rate-limiting after several retries; try again later.")

    def _paginate(self, url: str, params: dict) -> Iterator[dict]:
        body = self._get(url, params)
        while True:
            yield from body.get("data", [])
            nxt = body.get("paging", {}).get("next")
            if not nxt:
                return
            body = self._get(nxt)  # next URL already carries all params

    # ---- accounts --------------------------------------------------------
    def list_ad_accounts(self) -> list[dict]:
        return list(self._paginate(
            f"{self.base}/me/adaccounts",
            {"fields": "account_id,name,currency,account_status", "limit": 200},
        ))

    # ---- insights --------------------------------------------------------
    def ad_insights(self, account_id: str, since: date, until: date) -> Iterator[dict]:
        """Daily, ad-level insight rows for one account, chunked to stay under Meta's size limits."""
        start = since
        while start <= until:
            end = min(until, start + timedelta(days=CHUNK_DAYS - 1))
            yield from self._insights_range(account_id, start, end)
            start = end + timedelta(days=1)

    def _insights_range(self, account_id: str, since: date, until: date) -> Iterator[dict]:
        params = {
            "level": "ad",
            "fields": ",".join(INSIGHT_FIELDS),
            "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
            "time_increment": 1,
            "limit": 500,
        }
        try:
            yield from self._paginate(f"{self.base}/{account_id}/insights", params)
        except MetaAPIError as e:
            # "Please reduce the amount of data" -> split the range and retry.
            if e.code == 1 and since < until:
                mid = since + (until - since) // 2
                yield from self._insights_range(account_id, since, mid)
                yield from self._insights_range(account_id, mid + timedelta(days=1), until)
            else:
                raise


# ---- row normalisation -----------------------------------------------------
LEAD_TYPES_FALLBACK = ("onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead")
MESSAGE_TYPE = "onsite_conversion.messaging_conversation_started_7d"


def _action_map(items: list[dict] | None) -> dict[str, float]:
    return {a["action_type"]: float(a.get("value", 0) or 0) for a in (items or [])}


def normalize_row(row: dict) -> dict:
    actions = _action_map(row.get("actions"))
    if "lead" in actions:  # "lead" is Meta's de-duplicated total when present
        leads = actions["lead"]
    else:
        leads = sum(actions.get(t, 0) for t in LEAD_TYPES_FALLBACK)
    thruplays = sum(_action_map(row.get("video_thruplay_watched_actions")).values())
    return {
        "ad_id": row["ad_id"],
        "date": row["date_start"],
        "account_id": f"act_{row['account_id']}",
        "account_name": row.get("account_name", ""),
        "currency": row.get("account_currency", ""),
        "campaign_id": row.get("campaign_id", ""),
        "campaign_name": row.get("campaign_name", ""),
        "objective": row.get("objective", ""),
        "adset_id": row.get("adset_id", ""),
        "adset_name": row.get("adset_name", ""),
        "ad_name": row.get("ad_name", ""),
        "spend": float(row.get("spend", 0) or 0),
        "impressions": int(float(row.get("impressions", 0) or 0)),
        "reach": int(float(row.get("reach", 0) or 0)),
        "clicks": int(float(row.get("clicks", 0) or 0)),
        "link_clicks": int(float(row.get("inline_link_clicks", 0) or 0)),
        "leads": leads,
        "messages": actions.get(MESSAGE_TYPE, 0.0),
        "video_3s": actions.get("video_view", 0.0),
        "thruplays": thruplays,
        "actions_json": json.dumps(row.get("actions") or []),
    }


ProgressFn = Callable[[str], None]
