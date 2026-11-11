"""Settings loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LIVE_DB = DATA_DIR / "chauffeur.db"
DEMO_DB = DATA_DIR / "demo.db"

load_dotenv(ROOT / ".env")


def _normalize_account_id(raw: str) -> str:
    raw = raw.strip()
    return raw if raw.startswith("act_") else f"act_{raw}"


@dataclass(frozen=True)
class Settings:
    access_token: str = ""
    account_ids: list[str] = field(default_factory=list)
    api_version: str = "v24.0"

    @property
    def has_token(self) -> bool:
        return bool(self.access_token)


def load_settings() -> Settings:
    ids = [
        _normalize_account_id(a)
        for a in os.getenv("META_AD_ACCOUNT_IDS", "").split(",")
        if a.strip()
    ]
    return Settings(
        access_token=os.getenv("META_ACCESS_TOKEN", "").strip(),
        account_ids=ids,
        api_version=os.getenv("META_API_VERSION", "v24.0").strip() or "v24.0",
    )
