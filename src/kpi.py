"""Prevod hodnôt z dokumentov na štvrťročné a ročné ukazovatele pre investorov."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import METRICS

ID_COLS = ["sector", "ticker", "company", "fiscal_year", "period", "period_end"]

# Výstupné ukazovatele: stĺpec → (slovenský názov, jednotka, skupina, vysvetlenie)
KPI_INFO: dict[str, tuple[str, str, str, str]] = {
    "revenue_musd":             ("Tržby", "mil. USD", "Rast", "Tržby vrátane ostatných prevádzkových výnosov"),
    "revenue_yoy_pct":          ("Rast tržieb r/r", "%", "Rast", "Zmena oproti rovnakému obdobiu minulého roka"),
    "net_income_musd":          ("Čistý zisk", "mil. USD", "Ziskovosť", "Zisk pripadajúci akcionárom spoločnosti"),
    "net_margin_pct":           ("Čistá marža", "%", "Ziskovosť", "Čistý zisk / tržby"),
    "ebitda_musd":              ("EBITDA", "mil. USD", "Ziskovosť", "Zisk pred zdanením + úroky + odpisy (približný výpočet)"),
    "eps_diluted":              ("EPS (zriedený)", "USD", "Ziskovosť", "Zisk na akciu; Q4 = rok − Q1..Q3 (aproximácia)"),
    "eps_yoy_pct":              ("Rast EPS r/r", "%", "Rast", "Zmena EPS oproti rovnakému obdobiu minulého roka"),
    "roe_pct":                  ("ROE", "%", "Ziskovosť", "Čistý zisk / vlastný kapitál; pri štvrťrokoch anualizované (×4)"),
    "operating_cash_flow_musd": ("Prevádzkový cash flow", "mil. USD", "Hotovosť", "Hotovosť vytvorená prevádzkou"),
    "capex_musd":               ("CAPEX", "mil. USD", "Hotovosť", "Investície do dlhodobého majetku"),
    "free_cash_flow_musd":      ("Voľný cash flow (FCF)", "mil. USD", "Hotovosť", "Prevádzkový cash flow − CAPEX"),
    "shareholder_returns_musd": ("Výplaty akcionárom", "mil. USD", "Akcionári", "Dividendy + spätné odkupy akcií"),
    "fcf_payout_pct":           ("Výplaty / FCF", "%", "Akcionári", "Nad 100 % = výplaty financované z dlhu alebo rezerv"),
    "net_debt_musd":            ("Čistý dlh", "mil. USD", "Zadlženosť", "Dlhodobý dlh + krátkodobé pôžičky + splatná časť dlhodobého dlhu − hotovosť (bez lízingov)"),
    "net_debt_to_equity":       ("Čistý dlh / vlastný kapitál", "x", "Zadlženosť", "Pod 0,3 nízka, nad 1 vysoká zadlženosť"),
    "net_debt_to_ebitda":       ("Čistý dlh / EBITDA", "x", "Zadlženosť", "Za koľko rokov by firma splatila dlh z EBITDA (TTM); nad 3 = vysoké"),
    # ocenenie – cena akcie ku koncu obdobia, ukazovatele za posledné 4 štvrťroky (TTM)
    "price_usd":                ("Cena akcie", "USD", "Ocenenie", "Zatváracia cena k poslednému obchodnému dňu obdobia"),
    "market_cap_musd":          ("Trhová kapitalizácia", "mil. USD", "Ocenenie", "Cena × zriedený počet akcií"),
    "pe_ttm":                   ("P/E", "x", "Ocenenie", "Cena / EPS za posledné 4 štvrťroky; nižšie = lacnejšie (pri strate sa neuvádza)"),
    "ev_ebitda_ttm":            ("EV/EBITDA", "x", "Ocenenie", "(Kapitalizácia + čistý dlh) / EBITDA za 4 štvrťroky; zohľadňuje aj dlh"),
    "pb":                       ("P/B", "x", "Ocenenie", "Kapitalizácia / účtovný vlastný kapitál"),
    "fcf_yield_pct":            ("FCF výnos", "%", "Ocenenie", "Voľný cash flow za 4 štvrťroky / kapitalizácia"),
    "dividend_yield_pct":       ("Dividendový výnos", "%", "Ocenenie", "Vyplatené dividendy za 4 štvrťroky / kapitalizácia"),
    "shareholder_yield_pct":    ("Výnos pre akcionárov", "%", "Ocenenie", "(Dividendy + spätné odkupy) za 4 štvrťroky / kapitalizácia"),
}
VALUATION_COLS = [c for c, v in KPI_INFO.items() if v[2] == "Ocenenie"]
OUTPUT_COLUMNS = ID_COLS + list(KPI_INFO) + ["data_check"]
CHECK_METRICS = ["revenue", "net_income", "eps_diluted", "operating_cash_flow", "capex", "pretax_income",
                 "depreciation", "dividends_paid", "buybacks", "cash", "total_equity", "long_term_debt",
                 "short_term_borrowings", "current_ltd"]
TTM_COLS = ["eps_diluted", "ebitda", "free_cash_flow", "dividends_paid", "buybacks", "net_income"]
BASE_COLS = ID_COLS + ["eps_ttm", "ebitda_ttm", "free_cash_flow_ttm", "dividends_paid_ttm", "buybacks_ttm",
                       "shares_diluted", "net_debt", "total_equity"]


def _quarterize(s: pd.Series, kind: str) -> pd.Series:
    """s: hodnoty z dokumentov Q1..Q4 (Q4 = 10-K za celý rok)."""
    s = s.reindex([1, 2, 3, 4]).astype(float)
    if kind == "instant":
        return s
    q = s.copy()
    if kind == "duration_q":           # Q1-Q3 priamo, Q4 = rok − (Q1+Q2+Q3)
        q[4] = s[4] - s.loc[[1, 2, 3]].sum(min_count=3)
    else:                              # cash flow je kumulatívny (YTD) → rozdiely
        q = s.diff()
        q[1] = s[1]
    return q


def periodize(values: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Dokumenty → riadky Q1..Q4 + FY s absolútnymi hodnotami metrík (USD)."""
    meta = values.drop_duplicates(["ticker", "fiscal_year", "fiscal_quarter"]).set_index(
        ["ticker", "fiscal_year", "fiscal_quarter"])
    wide = values.pivot_table(index=["ticker", "fiscal_year", "fiscal_quarter"], columns="metric",
                              values=value_col, aggfunc="first")
    frames = []
    for (ticker, fy), w in wide.groupby(level=[0, 1]):
        w = w.droplevel([0, 1])
        m = meta.loc[(ticker, fy)]
        q = pd.DataFrame({k: _quarterize(w[k] if k in w else pd.Series(dtype=float), spec["kind"])
                          for k, spec in METRICS.items()})
        q["period"] = [f"Q{i}" for i in q.index]
        q["period_end"] = [m["report_date"].get(i, "") for i in q.index]
        q["annualize"] = 4
        a = pd.DataFrame({k: [w[k].get(4, np.nan) if k in w else np.nan] for k in METRICS})
        a["period"], a["period_end"], a["annualize"] = "FY", m["report_date"].get(4, ""), 1
        f = pd.concat([q, a], ignore_index=True)
        info = m.iloc[0]
        f["ticker"], f["fiscal_year"], f["company"], f["sector"] = ticker, int(fy), info["company"], info["sector"]
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def _ttm(p: pd.DataFrame) -> pd.DataFrame:
    """Súčty za posledné 4 štvrťroky (TTM) – len ak idú 4 štvrťroky za sebou."""
    p = p.copy()
    for c in TTM_COLS:
        p[f"{c}_ttm"] = np.nan
    isq = p["period"] != "FY"
    for _, g in p[isq].groupby("ticker"):
        g = g.assign(_i=g["fiscal_year"] * 4 + g["period"].str[1].astype(int)).sort_values("_i")
        consecutive = (g["_i"] - g["_i"].shift(3)) == 3
        for c in TTM_COLS:
            src = g[c].fillna(0) if c in ("dividends_paid", "buybacks") else g[c]
            p.loc[g.index, f"{c}_ttm"] = src.rolling(4, min_periods=4).sum().where(consecutive)
    for c in TTM_COLS:  # pri ročnom riadku je TTM = celý rok
        p.loc[~isq, f"{c}_ttm"] = p.loc[~isq, c] if c not in ("dividends_paid", "buybacks") else p.loc[~isq, c].fillna(0)
    p = p.rename(columns={"eps_diluted_ttm": "eps_ttm"})
    return p


def _plausibility(p: pd.DataFrame) -> pd.DataFrame:
    """Vynechá ekonomicky nemožné hodnoty (typicky zlý riadok v jednom štvrťroku, ktorý po dopočte
    štvrťrokov z kumulatívnych hodnôt pokazí aj ďalšie obdobia) a zapíše ich do stĺpca _implausible."""
    p = p.copy()
    flags = [[] for _ in range(len(p))]
    rev = p["revenue"]

    def drop(metric: str, bad: pd.Series) -> None:
        bad = bad.fillna(False)
        for i in np.flatnonzero(bad.to_numpy()):
            flags[i].append(metric)
        p.loc[bad, metric] = np.nan

    for m in ("capex", "depreciation", "dividends_paid", "buybacks"):
        drop(m, (p[m] < 0) | ((m in ("capex", "depreciation")) & (rev > 0) & (p[m] > rev)))
    # úroky za obdobie nemôžu byť záporné ani vyššie ako polovica tržieb (inak ide napr. o celý dlh zo súvahy)
    drop("interest_expense", (p["interest_expense"] < 0) | ((rev > 0) & (p["interest_expense"] > 0.5 * rev)))
    # zisk pred zdanením − čistý zisk = dane a menšinové podiely; tie nemôžu byť väčšie ako tržby
    drop("pretax_income", (rev > 0) & ((p["pretax_income"] - p["net_income"]).abs() > rev))
    p["_implausible"] = [", ".join(f) for f in flags]
    return p


def _ratios(p: pd.DataFrame) -> pd.DataFrame:
    p = _plausibility(p)
    p["free_cash_flow"] = p["operating_cash_flow"] - p["capex"]
    p["shareholder_returns"] = p["dividends_paid"].fillna(0) + p["buybacks"].fillna(0)
    p["ebitda"] = p["pretax_income"] + p["interest_expense"].fillna(0) + p["depreciation"]
    too_big = (p["revenue"] > 0) & (p["ebitda"] > p["revenue"])  # EBITDA nemôže byť vyššia ako tržby
    p.loc[too_big, "_implausible"] = [", ".join(filter(None, [f, "ebitda"])) for f in p.loc[too_big, "_implausible"]]
    p.loc[too_big, "ebitda"] = np.nan
    p["net_debt"] = (p["long_term_debt"] + p["short_term_borrowings"].fillna(0) + p["current_ltd"].fillna(0)
                     - p["cash"])
    p["net_margin_pct"] = 100 * p["net_income"] / p["revenue"]
    p["fcf_payout_pct"] = np.where(p["free_cash_flow"] > 0, 100 * p["shareholder_returns"] / p["free_cash_flow"], np.nan)
    p["net_debt_to_equity"] = p["net_debt"] / p["total_equity"]
    p["roe_pct"] = 100 * p["annualize"] * p["net_income"] / p["total_equity"]
    # zriedený počet akcií = čistý zisk / EPS (pri malom EPS by zaokrúhlenie skreslilo → berieme ročný)
    shares = np.where(p["eps_diluted"].abs() >= 0.3, p["net_income"] / p["eps_diluted"], np.nan)
    p["shares_diluted"] = pd.Series(shares, index=p.index).where(p["period"] != "Q4")
    fy_shares = p[p["period"] == "FY"].set_index(["ticker", "fiscal_year"])["shares_diluted"]
    fill = p.set_index(["ticker", "fiscal_year"]).index.map(fy_shares.get)
    p["shares_diluted"] = p["shares_diluted"].fillna(pd.Series(fill, index=p.index, dtype=float))
    # počet akcií sa mení pomaly → ak v období chýba EPS, prevezme sa z najbližšieho obdobia tej istej firmy
    # (inak by chýbala kapitalizácia aj P/B, FCF a dividendový výnos, hoci nezávisia od zisku)
    order = p["fiscal_year"] * 10 + p["period"].map({"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4.5})
    p = p.assign(_o=order).sort_values(["ticker", "_o"])
    p["shares_diluted"] = p.groupby("ticker")["shares_diluted"].transform(lambda x: x.ffill().bfill())
    p = p.drop(columns="_o").sort_index()
    p = _ttm(p)
    p["net_debt_to_ebitda"] = np.where(p["ebitda_ttm"] > 0, p["net_debt"] / p["ebitda_ttm"], np.nan)
    prev = p[["ticker", "fiscal_year", "period", "revenue", "eps_diluted"]].copy()
    prev["fiscal_year"] += 1
    p = p.merge(prev, on=["ticker", "fiscal_year", "period"], how="left", suffixes=("", "_prev"))
    p["revenue_yoy_pct"] = 100 * (p["revenue"] - p["revenue_prev"]) / p["revenue_prev"].abs()
    p["eps_yoy_pct"] = 100 * (p["eps_diluted"] - p["eps_diluted_prev"]) / p["eps_diluted_prev"].abs()
    return p


def _close(metric: str, a: float, b: float) -> bool:
    if metric == "eps_diluted":
        return abs(a - b) <= 0.02
    return abs(a - b) <= max(0.01 * abs(b), 1e6)


def _data_check(nlp: pd.DataFrame, ref: pd.DataFrame) -> pd.Series:
    """Porovná NLP hodnoty s oficiálnymi XBRL hodnotami → OK / Skontroluj / Chýba."""
    key = ["ticker", "fiscal_year", "period"]
    r = ref.set_index(key)
    out = []
    for _, row in nlp.iterrows():
        k = tuple(row[c] for c in key)
        if k not in r.index:
            out.append(f"Bez referencie; nepravdepodobné: {row['_implausible']}" if row.get("_implausible")
                       else "Bez referencie")
            continue
        rr = r.loc[k]
        wrong = [m for m in CHECK_METRICS if pd.notna(row[m]) and pd.notna(rr[m]) and not _close(m, row[m], rr[m])]
        missing = [m for m in CHECK_METRICS if pd.isna(row[m]) and pd.notna(rr[m])]
        msg = []
        if row.get("_implausible"):
            msg.append("Nepravdepodobné (vynechané): " + row["_implausible"])
        if wrong:
            msg.append("Skontroluj: " + ", ".join(wrong))
        if missing:
            msg.append("Chýba: " + ", ".join(missing))
        out.append("; ".join(msg) or "OK")
    return pd.Series(out, index=nlp.index)


def _sort(p: pd.DataFrame) -> pd.DataFrame:
    p = p.assign(_order=p["period"].map({"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}))
    return p.sort_values(["sector", "ticker", "fiscal_year", "_order"]).drop(columns="_order")


def format_output(p: pd.DataFrame) -> pd.DataFrame:
    """USD → mil. USD, zaokrúhlenie, poradie stĺpcov podľa OUTPUT_COLUMNS."""
    p = p.copy()
    for c in ["revenue", "net_income", "ebitda", "operating_cash_flow", "capex", "free_cash_flow",
              "shareholder_returns", "net_debt", "market_cap"]:
        if c in p:
            p[f"{c}_musd"] = (p[c] / 1e6).round(0)
    for c, (_, unit, _, _) in KPI_INFO.items():
        if c in p and not c.endswith("_musd"):
            p[c] = p[c].astype(float).round(1 if unit == "%" or c in ("pe_ttm", "ev_ebitda_ttm", "pb") else 2)
    return _sort(p)[[c for c in OUTPUT_COLUMNS if c in p]].reset_index(drop=True)


def build_investor_table(extracted: pd.DataFrame, gold: pd.DataFrame
                         ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Vráti (investorská tabuľka z NLP, tá istá z XBRL referencie, podklady pre ocenenie)."""
    meta = extracted[["doc_id", "ticker", "company", "sector", "fiscal_year", "fiscal_quarter",
                      "report_date"]].drop_duplicates("doc_id")
    gold = gold[["doc_id", "metric", "gold_value"]].merge(meta, on="doc_id")
    nlp = _ratios(periodize(extracted, "value"))
    ref = _ratios(periodize(gold, "gold_value"))
    nlp["data_check"] = _data_check(nlp, ref)
    ref["data_check"] = "XBRL referencia"
    base = _sort(nlp)[BASE_COLS].reset_index(drop=True)
    return format_output(nlp), format_output(ref), base


def upsert(path, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Prepíše riadky pre rovnaké kľúče, ostatné (napr. iné odvetvia) ponechá."""
    if path.exists():
        old = pd.read_csv(path)
        mark = new[keys].drop_duplicates().assign(_new=1)
        old = old.merge(mark, on=keys, how="left")
        old = old[old["_new"].isna()].drop(columns="_new")
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(path, index=False, encoding="utf-8-sig")  # utf-8-sig = diakritika OK aj v Exceli
    return new
