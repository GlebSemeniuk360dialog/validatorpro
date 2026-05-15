"""
schedule.py — G-Sheet schedule fetching and client schedule lookup.
No Streamlit cache here — caching is applied at the call site in app.py
so it can be invalidated by the user.
"""

import logging
from datetime import datetime

import pandas as pd
from dateutil import parser as dateutil_parser

from config import CLIENT_ALIASES, GSHEET_COLS

logger = logging.getLogger(__name__)


def fetch_gsheet_data_csv(csv_url: str) -> list[dict]:
    """
    Download a published Google Sheet as CSV and return rows as dicts.
    Returns [] on failure.
    """
    try:
        df = pd.read_csv(csv_url)
        df.columns = df.columns.str.strip()
        return df.fillna("").astype(str).to_dict("records")
    except Exception as exc:
        logger.warning("fetch_gsheet_data_csv failed for %s: %s", csv_url, exc)
        return []


def get_client_schedule(sheet_data: list[dict], client_name: str) -> list[dict]:
    """
    Return rows from *sheet_data* that match *client_name* and fall within
    ±1..+8 days of today, sorted by date ascending.
    """
    if not sheet_data or not client_name:
        return []

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Build the set of names to match (canonical + aliases)
    target_names = {client_name.lower()}
    for alias in CLIENT_ALIASES.get(client_name, []):
        target_names.add(alias.lower())

    results: list[dict] = []
    for row in sheet_data:
        row_client = str(row.get(GSHEET_COLS["client"], "")).strip().lower()
        if not any(alias in row_client for alias in target_names):
            continue

        try:
            row_date = dateutil_parser.parse(
                str(row.get(GSHEET_COLS["date"], "")), dayfirst=True
            ).replace(hour=0, minute=0, second=0, microsecond=0)
        except (ValueError, OverflowError):
            continue

        delta = (row_date - today).days
        if not (-1 <= delta <= 8):
            continue

        row = dict(row)  # don't mutate the original
        row["_parsed_date"] = row_date
        row["_display_str"] = (
            f"{row_date.strftime('%Y-%m-%d')} | "
            f"{str(row.get(GSHEET_COLS['client'], ''))[:30]} | "
            f"In: {row.get(GSHEET_COLS['include_tags'], '')} | "
            f"Ex: {row.get(GSHEET_COLS['exclude_tags'], '')}"
        )
        results.append(row)

    return sorted(results, key=lambda r: r["_parsed_date"])


def get_client_schedule_wide(sheet_data: list[dict], client_name: str,
                              days_back: int = 3, days_forward: int = 30) -> list[dict]:
    """
    Like get_client_schedule but with a wider date window.
    Used by the control panel so tickets validated in advance still match.
    """
    if not sheet_data or not client_name:
        return []

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    target_names = {client_name.lower()}
    for alias in CLIENT_ALIASES.get(client_name, []):
        target_names.add(alias.lower())

    results: list[dict] = []
    for row in sheet_data:
        row_client = str(row.get(GSHEET_COLS["client"], "")).strip().lower()
        if not any(alias in row_client for alias in target_names):
            continue
        try:
            row_date = dateutil_parser.parse(
                str(row.get(GSHEET_COLS["date"], "")), dayfirst=True
            ).replace(hour=0, minute=0, second=0, microsecond=0)
        except (ValueError, OverflowError):
            continue

        delta = (row_date - today).days
        if not (-days_back <= delta <= days_forward):
            continue

        row = dict(row)
        row["_parsed_date"] = row_date
        row["_display_str"] = (
            f"{row_date.strftime('%Y-%m-%d')} | "
            f"{str(row.get(GSHEET_COLS['client'], ''))[:30]} | "
            f"In: {row.get(GSHEET_COLS['include_tags'], '')} | "
            f"Ex: {row.get(GSHEET_COLS['exclude_tags'], '')}"
        )
        results.append(row)

    return sorted(results, key=lambda r: r["_parsed_date"])
