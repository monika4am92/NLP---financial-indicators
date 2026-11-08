"""Katalóg odvetví a spoločností (catalog/companies.csv) + dohľadanie CIK zo SEC."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .config import CATALOG_PATH

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"  # oficiálny zoznam ticker → CIK


def load_catalog(path: Path = CATALOG_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    df["ticker"] = df["ticker"].str.upper().str.strip()
    if "cik" not in df:
        df["cik"] = ""
    return df.drop_duplicates("ticker", keep="last")


def sectors(df: pd.DataFrame | None = None) -> list[str]:
    df = load_catalog() if df is None else df
    return list(dict.fromkeys(df["sector"]))  # poradie ako v súbore


def companies_in(sector: str, df: pd.DataFrame | None = None) -> pd.DataFrame:
    df = load_catalog() if df is None else df
    return df[df["sector"] == sector]


def add_company(ticker: str, sector: str, subsector: str = "", name: str = "", cik: str = "",
                path: Path = CATALOG_PATH) -> None:
    df = load_catalog(path)
    row = pd.DataFrame([{"sector": sector.strip(), "subsector": subsector.strip(),
                         "ticker": ticker.upper().strip(), "name": name.strip() or ticker.upper(),
                         "cik": cik.strip()}])
    pd.concat([df[df.ticker != ticker.upper().strip()], row]).to_csv(path, index=False)


def catalog_ciks(ticker: str, df: pd.DataFrame | None = None) -> list[int]:
    """CIK z katalógu (napr. '2115436;34088' = nová holdingová firma + pôvodný emitent)."""
    df = load_catalog() if df is None else df
    row = df[df["ticker"] == ticker.upper()]
    raw = row.iloc[0]["cik"] if len(row) else ""
    return [int(x) for x in str(raw).replace(",", ";").split(";") if x.strip().isdigit()]


def ticker_map(client, cache: Path) -> dict[str, dict]:
    """ticker → {cik, title}; stiahne sa raz a uloží do cache."""
    if not cache.exists():
        cache.write_text(json.dumps(client.get_json(TICKERS_URL)), encoding="utf-8")
    raw = json.loads(cache.read_text(encoding="utf-8"))
    return {v["ticker"].upper(): {"cik": int(v["cik_str"]), "title": v["title"]} for v in raw.values()}
