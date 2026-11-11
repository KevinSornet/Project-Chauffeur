"""Generate realistic fake boost data so the dashboard can be explored without a token."""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from .config import DEMO_DB
from .store import connect, upsert_rows

ACCOUNTS = [
    ("act_1001", "Demo – Main Page"),
    ("act_1002", "Demo – Branch North"),
    ("act_1003", "Demo – Branch South"),
    ("act_1004", "Demo – Promo Page"),
]
POSTS = [
    ("Airport transfer promo", "LINK_CLICKS", "video"),
    ("Wedding car package", "OUTCOME_LEADS", "image"),
    ("Holiday fleet reel", "VIDEO_VIEWS", "video"),
    ("Book via Messenger", "OUTCOME_ENGAGEMENT", "image"),
    ("Corporate shuttle offer", "OUTCOME_LEADS", "image"),
    ("Driver spotlight", "OUTCOME_AWARENESS", "video"),
]


def generate(days: int = 120, db_path: Path = DEMO_DB, seed: int = 7) -> int:
    rng = random.Random(seed)
    today = date.today()
    rows = []
    for acct_idx, (acct, acct_name) in enumerate(ACCOUNTS):
        quality = 0.8 + acct_idx * 0.15  # accounts differ in efficiency
        for post_idx, (post, objective, media) in enumerate(POSTS):
            if rng.random() < 0.25:
                continue
            ad_id = f"{acct[4:]}{post_idx:03d}"
            start = rng.randint(0, days - 20)
            length = rng.randint(7, 45)
            budget = rng.choice([5, 10, 20, 40])
            for d in range(start, min(days, start + length)):
                day = today - timedelta(days=days - 1 - d)
                spend = budget * rng.uniform(0.7, 1.15)
                cpm = rng.uniform(2.5, 7) * quality
                impressions = int(spend / cpm * 1000)
                reach = int(impressions / rng.uniform(1.1, 1.8))
                ctr = rng.uniform(0.006, 0.02) / quality * (1.4 if objective == "LINK_CLICKS" else 1)
                link_clicks = int(impressions * ctr)
                leads = link_clicks * rng.uniform(0.04, 0.12) if objective == "OUTCOME_LEADS" else 0
                messages = link_clicks * rng.uniform(0.05, 0.15) if objective == "OUTCOME_ENGAGEMENT" else 0
                v3 = impressions * rng.uniform(0.15, 0.35) if media == "video" else 0
                thru = v3 * rng.uniform(0.2, 0.45)
                rows.append({
                    "ad_id": ad_id, "date": day.isoformat(),
                    "account_id": acct, "account_name": acct_name, "currency": "USD",
                    "campaign_id": f"c{ad_id}", "campaign_name": f'Post: "{post}"',
                    "objective": objective, "adset_id": f"s{ad_id}", "adset_name": f"{post} – audience",
                    "ad_name": f'Post: "{post}"',
                    "spend": round(spend, 2), "impressions": impressions, "reach": reach,
                    "clicks": int(link_clicks * 1.6), "link_clicks": link_clicks,
                    "leads": round(leads), "messages": round(messages),
                    "video_3s": round(v3), "thruplays": round(thru), "actions_json": "[]",
                })
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    try:
        return upsert_rows(conn, rows)
    finally:
        conn.close()


if __name__ == "__main__":
    print(f"Wrote {generate()} demo rows to {DEMO_DB}")
