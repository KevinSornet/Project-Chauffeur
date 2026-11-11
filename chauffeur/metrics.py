"""Aggregation and derived boost-performance metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd

SUM_COLS = ["spend", "impressions", "reach", "clicks", "link_clicks", "leads", "messages", "video_3s", "thruplays"]

# key -> (label, kind) ; kind drives formatting
METRICS: dict[str, tuple[str, str]] = {
    "spend": ("Spend", "money"),
    "impressions": ("Impressions", "int"),
    "reach": ("Reach (sum of daily)", "int"),
    "frequency": ("Frequency", "ratio"),
    "cpm": ("CPM", "money"),
    "link_clicks": ("Link clicks", "int"),
    "ctr": ("Link CTR", "pct"),
    "cpc": ("Cost per link click", "money"),
    "leads": ("Leads", "int"),
    "cpl": ("Cost per lead", "money"),
    "messages": ("Messaging convos", "int"),
    "cost_per_message": ("Cost per message", "money"),
    "video_3s": ("3-sec video views", "int"),
    "thruplays": ("ThruPlays", "int"),
    "cost_per_thruplay": ("Cost per ThruPlay", "money"),
    "thruplay_rate": ("ThruPlay rate", "pct"),
}

# For cost metrics a decrease is good.
LOWER_IS_BETTER = {"cpm", "cpc", "cpl", "cost_per_message", "cost_per_thruplay"}


def _div(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(b > 0, a / b, np.nan)
    return out


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["frequency"] = _div(df["impressions"], df["reach"])
    df["cpm"] = _div(df["spend"], df["impressions"]) * 1000
    df["ctr"] = _div(df["link_clicks"], df["impressions"])
    df["cpc"] = _div(df["spend"], df["link_clicks"])
    df["cpl"] = _div(df["spend"], df["leads"])
    df["cost_per_message"] = _div(df["spend"], df["messages"])
    df["cost_per_thruplay"] = _div(df["spend"], df["thruplays"])
    df["thruplay_rate"] = _div(df["thruplays"], df["impressions"])
    return df


def aggregate(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    if by:
        out = df.groupby(by, as_index=False, dropna=False)[SUM_COLS].sum()
    else:
        out = pd.DataFrame([df[SUM_COLS].sum()])
    return add_derived(out)


def totals(df: pd.DataFrame) -> dict[str, float]:
    return aggregate(df).iloc[0].to_dict()


def fmt(value: float, kind: str, currency: str = "") -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if kind == "money":
        return f"{currency} {value:,.2f}".strip()
    if kind == "int":
        return f"{value:,.0f}"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    return f"{value:,.2f}"


def is_boosted_post(df: pd.DataFrame) -> pd.Series:
    """Heuristic: Meta names boosted-post campaigns/ads 'Post: "…"' by default."""
    pat = r"^\s*(Post:|Boosted|Boost)"
    return (
        df["campaign_name"].fillna("").str.contains(pat, case=False, regex=True)
        | df["ad_name"].fillna("").str.contains(pat, case=False, regex=True)
    )
