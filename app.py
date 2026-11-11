"""Project Chauffeur — Facebook boost performance dashboard.

Run:  streamlit run app.py
"""
from __future__ import annotations

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from chauffeur import demo
from chauffeur.config import DEMO_DB, LIVE_DB, load_settings
from chauffeur.meta_api import MetaAPIError
from chauffeur.metrics import LOWER_IS_BETTER, METRICS, aggregate, fmt, is_boosted_post, totals
from chauffeur.store import last_sync, load_insights
from chauffeur.sync import run_sync

st.set_page_config(page_title="Boost Performance", page_icon="📈", layout="wide")

# Categorical palette (validated reference order); slots beyond 7 fold to "Other".
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
OTHER = "#9a9893"

settings = load_settings()


@st.cache_data(show_spinner=False)
def get_data(path_str: str, mtime: float) -> pd.DataFrame:  # mtime busts the cache after a sync
    from pathlib import Path
    return load_insights(Path(path_str))


def db_mtime(path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


# ---------------------------------------------------------------- sidebar: source & sync
with st.sidebar:
    st.header("Data")
    default_source = 0 if (settings.has_token or LIVE_DB.exists()) else 1
    source = st.radio("Source", ["Live (Meta API)", "Demo data"], index=default_source, horizontal=True)
    live = source.startswith("Live")
    db_path = LIVE_DB if live else DEMO_DB

    if live:
        if not settings.has_token:
            st.warning("No `META_ACCESS_TOKEN` in `.env`. Copy `.env.example` to `.env` and add a token to sync.")
        else:
            accts = ", ".join(settings.account_ids) if settings.account_ids else "all accounts the token can see"
            st.caption(f"Accounts: {accts}")
            days = st.number_input("Days to (re)fetch", 1, 1095, 30,
                                   help="Meta revises recent numbers for ~28 days, so re-syncing overlaps on purpose.")
            if st.button("Sync from Meta", type="primary", width="stretch"):
                log = st.empty()
                lines: list[str] = []

                def progress(msg: str) -> None:
                    lines.append(msg)
                    log.code("\n".join(lines[-8:]))

                try:
                    with st.spinner("Syncing…"):
                        results = run_sync(int(days), settings=settings, progress=progress)
                    bad = [r for r in results if not r.ok]
                    if bad:
                        st.error("\n\n".join(f"{r.account_id}: {r.message}" for r in bad))
                    else:
                        st.success(f"Synced {sum(r.rows for r in results):,} rows from {len(results)} account(s).")
                except MetaAPIError as e:
                    st.error(str(e))
        ls = last_sync(LIVE_DB)
        if not ls.empty:
            st.caption("Last sync: " + ls["last_sync"].max().replace("T", " ") + " UTC")
    else:
        if not DEMO_DB.exists() or st.button("Regenerate demo data", width="stretch"):
            demo.generate()

raw = get_data(str(db_path), db_mtime(db_path))

st.title("Facebook boost performance")
if raw.empty:
    st.info("No data yet. Sync from Meta in the sidebar, or switch to **Demo data** to explore the dashboard.")
    st.stop()

# ---------------------------------------------------------------- sidebar: filters
with st.sidebar:
    st.header("Filters")
    dmin, dmax = raw["date"].min().date(), raw["date"].max().date()
    default_start = max(dmin, dmax - timedelta(days=29))
    picked = st.date_input("Date range", (default_start, dmax), min_value=dmin, max_value=dmax)
    start, end = (picked if isinstance(picked, (list, tuple)) and len(picked) == 2 else (picked[0], picked[0]))

    currencies = sorted(raw["currency"].dropna().unique())
    currency = currencies[0] if currencies else ""
    if len(currencies) > 1:
        currency = st.selectbox("Currency", currencies,
                                help="Accounts in different currencies can't be summed, so view one at a time.")
    pool = raw[raw["currency"] == currency] if currency else raw

    account_names = (pool.groupby("account_name")["spend"].sum().sort_values(ascending=False).index.tolist())
    chosen_accounts = st.multiselect("Accounts", account_names, default=account_names)
    objectives = sorted(pool["objective"].dropna().unique())
    chosen_obj = st.multiselect("Objective", objectives, default=objectives)
    boosted_only = st.toggle("Boosted posts only", value=False,
                             help='Keeps campaigns/ads whose name starts with "Post:" — Meta\'s default naming for boosts.')
    search = st.text_input("Search campaign / ad name")

# Stable color per account, assigned by all-time spend (never repainted by filters).
color_of = {name: SERIES[i] for i, name in enumerate(account_names[: len(SERIES)])}


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    df = df[df["account_name"].isin(chosen_accounts) & df["objective"].isin(chosen_obj)]
    if boosted_only:
        df = df[is_boosted_post(df)]
    if search:
        mask = (df["campaign_name"].str.contains(search, case=False, na=False)
                | df["ad_name"].str.contains(search, case=False, na=False))
        df = df[mask]
    return df


scoped = apply_filters(pool)
period = scoped[(scoped["date"].dt.date >= start) & (scoped["date"].dt.date <= end)]
span = (end - start).days + 1
prev_start, prev_end = start - timedelta(days=span), start - timedelta(days=1)
previous = scoped[(scoped["date"].dt.date >= prev_start) & (scoped["date"].dt.date <= prev_end)]

if period.empty:
    st.warning("No rows match these filters.")
    st.stop()

st.caption(f"{start:%b %d, %Y} – {end:%b %d, %Y} · {len(chosen_accounts)} account(s) · "
           f"compared with previous {span} days ({prev_start:%b %d} – {prev_end:%b %d})")

# ---------------------------------------------------------------- KPI tiles
cur, prv = totals(period), totals(previous) if not previous.empty else {}


def compact(v: float) -> str:
    if v is None or pd.isna(v):
        return "—"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div * 10:
            return f"{v / div:,.1f}{suf}"
    return f"{v:,.0f}"


def tile(col, key: str) -> None:
    label, kind = METRICS[key]
    value = cur.get(key)
    delta, color = None, "normal"
    p = prv.get(key)
    if p and pd.notna(p) and p != 0 and pd.notna(value):
        delta = f"{(value - p) / p * 100:+.1f}%"
        color = "inverse" if key in LOWER_IS_BETTER else "normal"
    if key == "frequency":
        color = "off"  # neither direction is inherently good
    shown = compact(value) if kind == "int" else fmt(value, kind)
    col.metric(f"{label} ({currency})" if kind == "money" and currency else label, shown, delta,
               delta_color=color, help=f"Exact: {fmt(value, kind, currency)}")


groups = [
    ("Spend & reach", ["spend", "impressions", "reach", "cpm", "frequency"]),
    ("Clicks & leads", ["link_clicks", "ctr", "cpc", "leads", "cpl"]),
    ("Video", ["video_3s", "thruplays", "cost_per_thruplay", "thruplay_rate", "messages"]),
]
for title, keys in groups:
    st.markdown(f"**{title}**")
    for c, k in zip(st.columns(len(keys)), keys):
        tile(c, k)

# ---------------------------------------------------------------- tabs
tab_acct, tab_trend, tab_boosts, tab_data = st.tabs(["By account", "Trend", "Top boosts", "Raw data"])
metric_options = list(METRICS)
label_of = {k: v[0] for k, v in METRICS.items()}


def display_table(df: pd.DataFrame, id_cols: list[str]) -> pd.DataFrame:
    keep = id_cols + [k for k in METRICS if k in df.columns]
    out = df[keep].rename(columns={**label_of, "account_name": "Account", "campaign_name": "Campaign",
                                   "ad_name": "Ad", "objective": "Objective"})
    return out


def column_config() -> dict:
    cfg = {}
    for k, (label, kind) in METRICS.items():
        if kind == "money":
            cfg[label] = st.column_config.NumberColumn(label, format=f"{currency} %.2f")
        elif kind == "int":
            cfg[label] = st.column_config.NumberColumn(label, format="localized")
        elif kind == "pct":
            cfg[label] = st.column_config.NumberColumn(label, format="percent")
        else:
            cfg[label] = st.column_config.NumberColumn(label, format="%.2f")
    return cfg


with tab_acct:
    by_acct = aggregate(period, ["account_name"]).sort_values("spend", ascending=False)
    m = st.selectbox("Compare accounts on", metric_options, index=metric_options.index("cpl"),
                     format_func=label_of.get, key="acct_metric")
    label, kind = METRICS[m]
    chart_df = by_acct[["account_name", m]].dropna()
    chart_df["color"] = chart_df["account_name"].map(lambda a: color_of.get(a, OTHER))
    chart_df["shown"] = chart_df[m].map(lambda v: fmt(v, kind, currency))
    order = chart_df.sort_values(m, ascending=m in LOWER_IS_BETTER)["account_name"].tolist()
    bars = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4, height={"band": 0.7}).encode(
        y=alt.Y("account_name:N", sort=order, title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X(f"{m}:Q", title=label, axis=alt.Axis(grid=True, gridOpacity=0.3),
                scale=alt.Scale(domainMax=float(chart_df[m].max() or 0) * 1.18 if not chart_df.empty else None)),
        color=alt.Color("color:N", scale=None),
        tooltip=[alt.Tooltip("account_name:N", title="Account"), alt.Tooltip("shown:N", title=label)],
    )
    text = bars.mark_text(align="left", dx=6, color="#52514e").encode(text="shown:N", color=alt.value("#52514e"))
    st.altair_chart((bars + text).properties(height=max(160, 44 * len(chart_df))), width="stretch")
    if m in LOWER_IS_BETTER:
        st.caption("Lower is better — best account is at the top.")
    st.dataframe(display_table(by_acct, ["account_name"]), hide_index=True,
                 width="stretch", column_config=column_config())

with tab_trend:
    c1, c2 = st.columns([3, 1])
    tm = c1.selectbox("Metric", metric_options, index=0, format_func=label_of.get, key="trend_metric")
    grain = c2.radio("Grain", ["Day", "Week"], horizontal=True, index=0 if span <= 45 else 1)
    tdf = period.copy()
    if grain == "Week":
        tdf["date"] = tdf["date"].dt.to_period("W-SUN").dt.start_time
    tdf["series"] = tdf["account_name"].where(tdf["account_name"].isin(color_of), "Other")
    trend = aggregate(tdf, ["date", "series"])
    tlabel, tkind = METRICS[tm]
    trend["shown"] = trend[tm].map(lambda v: fmt(v, tkind, currency))
    domain = [a for a in account_names if a in set(trend["series"])] + (["Other"] if "Other" in set(trend["series"]) else [])
    rng = [color_of.get(a, OTHER) for a in domain]
    hover = alt.selection_point(fields=["date"], nearest=True, on="pointerover", empty=False, clear="pointerout")
    base = alt.Chart(trend).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y(f"{tm}:Q", title=tlabel, axis=alt.Axis(gridOpacity=0.3)),
        color=alt.Color("series:N", scale=alt.Scale(domain=domain, range=rng),
                        legend=alt.Legend(title=None, orient="top")),
    )
    lines = base.mark_line(strokeWidth=2, interpolate="monotone")
    points = base.mark_point(filled=True, size=70, stroke="white", strokeWidth=2).encode(
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("date:T", title=grain), alt.Tooltip("series:N", title="Account"),
                 alt.Tooltip("shown:N", title=tlabel)],
    ).add_params(hover)
    rule = alt.Chart(trend).mark_rule(color="#9a9893").encode(x="date:T").transform_filter(hover)
    st.altair_chart((lines + rule + points).properties(height=380), width="stretch")
    if tm == "reach":
        st.caption("Reach is summed across days and ads, so it overstates unique people reached.")

with tab_boosts:
    c1, c2, c3 = st.columns([2, 1, 1])
    sort_metric = c1.selectbox("Rank boosts by", metric_options, index=metric_options.index("spend"),
                               format_func=label_of.get, key="boost_metric")
    min_spend = c2.number_input(f"Min spend ({currency})", 0.0, value=0.0, step=10.0)
    top_n = c3.number_input("Show", 5, 500, 25, step=5)
    by_ad = aggregate(period, ["account_name", "campaign_name", "ad_name", "objective"])
    by_ad = by_ad[by_ad["spend"] >= min_spend].dropna(subset=[sort_metric])
    by_ad = by_ad.sort_values(sort_metric, ascending=sort_metric in LOWER_IS_BETTER).head(int(top_n))
    st.dataframe(display_table(by_ad, ["account_name", "campaign_name", "ad_name", "objective"]),
                 hide_index=True, width="stretch", column_config=column_config())

with tab_data:
    export = period.drop(columns=["actions_json"], errors="ignore").sort_values(["date", "account_name"])
    st.dataframe(export, hide_index=True, width="stretch")
    st.download_button("Download CSV", export.to_csv(index=False).encode(),
                       file_name=f"boosts_{start}_{end}.csv", mime="text/csv")
