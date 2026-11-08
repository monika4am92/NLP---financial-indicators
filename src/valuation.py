"""Ocenenie: trhové ceny akcií + P/E, EV/EBITDA, P/B a výnosové ukazovatele.

Ceny: Yahoo Finance cez knižnicu yfinance (bezplatné, bez API kľúča, neoficiálne rozhranie).
Ak nefunguje, ceny možno doplniť ručne do catalog/manual_prices.csv (ticker,date,close).
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from .config import ROOT, Paths
from .kpi import KPI_INFO, OUTPUT_COLUMNS, VALUATION_COLS, format_output, upsert

MANUAL_PRICES = ROOT / "catalog" / "manual_prices.csv"
DISCLAIMER = ("Informatívne údaje, nie investičné odporúčanie. Ocenenie vychádza z ceny akcie a výkazov; "
              "pred rozhodnutím over čísla v oficiálnych dokumentoch.")


def fetch_prices(tickers: list[str], start: str, log: Callable = print) -> pd.DataFrame:
    """Denné zatváracie ceny (neupravené o dividendy) z Yahoo Finance."""
    empty = pd.DataFrame(columns=["ticker", "date", "close"])
    try:
        import yfinance as yf
    except ImportError:
        log("  ! knižnica yfinance nie je nainštalovaná (pip install yfinance) – ocenenie preskočené")
        return empty
    ymap = {t: t.replace(".", "-") for t in tickers}  # BRK.B → BRK-B
    try:
        data = yf.download(list(ymap.values()), start=start, auto_adjust=False, progress=False,
                           multi_level_index=True)
    except Exception as e:  # noqa: BLE001
        log(f"  ! ceny sa nepodarilo stiahnuť: {e}")
        return empty
    if data is None or data.empty or "Close" not in data:
        log("  ! Yahoo Finance nevrátil žiadne ceny")
        return empty
    close = data["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(next(iter(ymap.values())))
    rev = {v: k for k, v in ymap.items()}
    long = close.rename(columns=rev).stack().reset_index()
    long.columns = ["date", "ticker", "close"]
    long["date"] = pd.to_datetime(long["date"]).dt.strftime("%Y-%m-%d")
    log(f"  ceny: {long.ticker.nunique()} firiem, {long.date.min()} – {long.date.max()}")
    return long[["ticker", "date", "close"]]


def load_prices(paths: Paths) -> pd.DataFrame:
    frames = [pd.read_csv(p) for p in (paths.output / "market_prices.csv", MANUAL_PRICES) if p.exists()]
    if not frames:
        return pd.DataFrame(columns=["ticker", "date", "close"])
    prices = pd.concat(frames).drop_duplicates(["ticker", "date"], keep="last")  # ručné ceny majú prednosť
    prices["date"] = pd.to_datetime(prices["date"])
    return prices.dropna(subset=["close"]).sort_values("date")


def _metrics(df: pd.DataFrame) -> pd.DataFrame:
    """df: price + podklady (TTM, akcie, dlh, VK) → ukazovatele ocenenia."""
    df = df.copy()
    df["market_cap"] = df["price_usd"] * df["shares_diluted"]
    ev = df["market_cap"] + df["net_debt"]
    df["pe_ttm"] = np.where(df["eps_ttm"] > 0, df["price_usd"] / df["eps_ttm"], np.nan)
    df["ev_ebitda_ttm"] = np.where(df["ebitda_ttm"] > 0, ev / df["ebitda_ttm"], np.nan)
    df["pb"] = np.where(df["total_equity"] > 0, df["market_cap"] / df["total_equity"], np.nan)
    df["fcf_yield_pct"] = 100 * df["free_cash_flow_ttm"] / df["market_cap"]
    df["dividend_yield_pct"] = 100 * df["dividends_paid_ttm"] / df["market_cap"]
    df["shareholder_yield_pct"] = 100 * (df["dividends_paid_ttm"] + df["buybacks_ttm"]) / df["market_cap"]
    return df


def period_valuation(base: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Ocenenie ku koncu každého obdobia (cena k poslednému obchodnému dňu ≤ koniec obdobia)."""
    b = base.copy()
    b["_d"] = pd.to_datetime(b["period_end"], errors="coerce")
    b = b.dropna(subset=["_d"]).sort_values("_d")
    if prices.empty:
        b["price_usd"] = np.nan
    else:
        b = pd.merge_asof(b, prices.rename(columns={"date": "_pd", "close": "price_usd"}).sort_values("_pd"),
                          left_on="_d", right_on="_pd", by="ticker", direction="backward",
                          tolerance=pd.Timedelta(days=10))
    return _metrics(b)


def current_valuation(base: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Aktuálne ocenenie: posledná cena + posledné 4 štvrťroky z výkazov."""
    q = base[(base["period"] != "FY") & base["eps_ttm"].notna()].copy()
    q["_d"] = pd.to_datetime(q["period_end"], errors="coerce")
    latest = q.sort_values("_d").groupby("ticker").tail(1)
    if prices.empty:
        return pd.DataFrame()
    last_px = prices.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    latest = latest[latest["ticker"].isin(last_px.index)].copy()
    latest["price_usd"] = latest["ticker"].map(last_px["close"])
    latest["price_date"] = latest["ticker"].map(last_px["date"].dt.strftime("%Y-%m-%d"))
    latest["basis"] = latest["fiscal_year"].astype(str) + " " + latest["period"]
    v = _metrics(latest)
    v["market_cap_musd"] = (v["market_cap"] / 1e6).round(0)
    for c in VALUATION_COLS:
        if c != "market_cap_musd":
            v[c] = v[c].astype(float).round(2 if c == "price_usd" else 1)
    cols = ["sector", "ticker", "company", "price_date", "basis"] + VALUATION_COLS
    return v[cols].sort_values(["sector", "ticker"]).reset_index(drop=True)


def refresh_valuation(paths: Paths, log: Callable = print, fetch: bool = True) -> pd.DataFrame:
    """Stiahne ceny, doplní ocenenie do investor_kpis.csv a uloží aktuálne ocenenie."""
    base_path = paths.audit / "valuation_base.csv"
    if not base_path.exists() or not paths.kpis.exists():
        log("  ! ešte nie sú spracované výkazy – najprv spusti spracovanie firiem")
        return pd.DataFrame()
    base = pd.read_csv(base_path)
    if fetch:
        start = (pd.to_datetime(base["period_end"]).min() - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
        new = fetch_prices(sorted(base["ticker"].unique()), start, log)
        if not new.empty:
            upsert(paths.output / "market_prices.csv", new, ["ticker", "date"])
    prices = load_prices(paths)

    val = period_valuation(base, prices)
    val = format_output(val)[["ticker", "fiscal_year", "period"] + [c for c in VALUATION_COLS]]
    kpis = pd.read_csv(paths.kpis)
    kpis = kpis.drop(columns=[c for c in VALUATION_COLS if c in kpis]).merge(
        val, on=["ticker", "fiscal_year", "period"], how="left")
    kpis[[c for c in OUTPUT_COLUMNS if c in kpis]].to_csv(paths.kpis, index=False, encoding="utf-8-sig")

    current = current_valuation(base, prices)
    current.to_csv(paths.output / "valuation_current.csv", index=False, encoding="utf-8-sig")
    log(f"  ocenenie doplnené ({int(kpis['price_usd'].notna().sum())} období s cenou, "
        f"{len(current)} firiem s aktuálnym ocenením)")
    return current
