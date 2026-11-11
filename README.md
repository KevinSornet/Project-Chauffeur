# Project Chauffeur — Facebook boost performance

A local Streamlit dashboard that pulls daily, ad-level insights from the **Meta Marketing API**
for each of your ad accounts, caches them in SQLite, and compares boost performance across accounts.

**Metrics:** spend, impressions, reach, frequency, CPM · link clicks, CTR, CPC, leads, cost per lead,
messaging conversations · 3-sec video views, ThruPlays, cost per ThruPlay, ThruPlay rate.
Every KPI shows the % change against the previous period of the same length.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in META_ACCESS_TOKEN (and optionally META_AD_ACCOUNT_IDS)
```

### Getting a token
1. Create an app at <https://developers.facebook.com/apps> (type: Business).
2. In **Business Settings → Users → System users**, create a system user, assign it your ad accounts
   (view performance is enough), and generate a token for the app with the `ads_read` permission.
3. Put it in `.env` as `META_ACCESS_TOKEN`. Leave `META_AD_ACCOUNT_IDS` empty to include every account
   the token can see, or list them comma-separated.

## Run

```bash
.venv/bin/streamlit run app.py
```

Click **Sync from Meta** in the sidebar (first time, try 90+ days). Or switch the source to **Demo data**
to explore with generated numbers. You can also sync from the command line (e.g. on a cron):

```bash
.venv/bin/python -m chauffeur.sync --days 30
```

## Notes
- Meta revises numbers for ~28 days after the fact, so re-syncing the last 30 days overwrites them.
- **Reach** is summed across days/ads, so it overstates unique people reached. Impressions are exact.
- Cost metrics (CPL, CPC, …) divide *all* spend in the filter by the result count; filter by
  objective for a like-for-like cost per result.
- Accounts in different currencies are viewed one currency at a time.
- "Boosted posts only" matches campaign/ad names starting with `Post:` (Meta's default for boosts).

## Layout
- `app.py` — dashboard
- `chauffeur/meta_api.py` — Graph API client (pagination, rate-limit backoff, range splitting)
- `chauffeur/sync.py` — fetch → SQLite (`data/chauffeur.db`)
- `chauffeur/metrics.py` — aggregation & derived metrics
- `chauffeur/demo.py` — demo data generator (`data/demo.db`)
