"""Streamlit aplikácia: prehľad finančných ukazovateľov extrahovaných NLP modelom.

Spustenie:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from src.catalog import add_company, companies_in, load_catalog, sectors
from src.config import DEFAULT_YEARS, ROOT, Paths, user_agent
from src.pipeline import read_status
from src.kpi import KPI_INFO, VALUATION_COLS
from src.valuation import DISCLAIMER

# Kategorická paleta (overená na farbosleposť); farba patrí firme, nie poradiu
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
PERIOD_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}

st.set_page_config(page_title="Finančné ukazovatele (NLP)", page_icon="📊", layout="wide")


# ---------- pomocné funkcie ----------
def label(col: str) -> str:
    name, unit, *_ = KPI_INFO[col]
    return f"{name} ({unit})"


def fmt(col: str, v) -> str:
    if pd.isna(v):
        return "–"
    unit = KPI_INFO[col][1]
    if unit == "mil. USD":
        return f"{v:,.0f}".replace(",", " ") + " mil. USD"
    if unit == "%":
        return f"{v:.1f} %"
    if unit == "x":
        return f"{v:.1f}×" if col in VALUATION_COLS else f"{v:.2f}×"
    return f"{v:.2f} USD"


def d3fmt(col: str) -> str:
    unit = KPI_INFO[col][1]
    if unit == "mil. USD":
        return ",.0f"
    return ",.1f" if unit == "%" or col in VALUATION_COLS and unit == "x" else ",.2f"


def num(col: str, v) -> str:
    """Číslo bez jednotky pre tabuľky (jednotka je v názve riadku)."""
    if pd.isna(v):
        return "–"
    unit = KPI_INFO[col][1]
    if unit == "mil. USD":
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:.1f}" if unit == "%" or (unit == "x" and col in VALUATION_COLS) else f"{v:.2f}"


@st.cache_data
def load_csv(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


def read(path) -> pd.DataFrame | None:
    return load_csv(str(path), path.stat().st_mtime) if path.exists() else None


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["fiscal_year"] = df["fiscal_year"].astype(int)
    df["period_label"] = df["fiscal_year"].astype(str) + " " + df["period"]
    df["period_key"] = df["fiscal_year"] * 10 + df["period"].map(PERIOD_ORDER)
    return df.sort_values(["ticker", "period_key"])


def color_scale(tickers: list[str]) -> alt.Scale:
    return alt.Scale(domain=tickers, range=PALETTE[:len(tickers)])


# ---------- spracovanie na pozadí ----------
def is_running(paths: Paths, status: dict) -> bool:
    """Beží spracovanie? (stav 'running' a log sa menil v posledných 20 minútach)"""
    if status.get("state") != "running":
        return False
    log = paths.audit / "last_run.log"
    last = log.stat().st_mtime if log.exists() else 0
    return time.time() - last < 20 * 60


def start_background(paths: Paths, tickers: list[str], years: list[int]) -> None:
    """Spustí main.py ako samostatný proces – kliknutie v aplikácii ho nepreruší."""
    paths.ensure()
    cmd = [sys.executable, str(ROOT / "main.py"), "run", "--tickers", *tickers,
           "--years", *map(str, years), "--workdir", str(paths.base)]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    (paths.audit / "last_run.log").write_text("Spúšťam spracovanie…\n", encoding="utf-8")
    (paths.audit / "status.json").write_text(json.dumps(
        {"state": "running", "step": "štart", "tickers": tickers, "years": years}), encoding="utf-8")
    err = (paths.audit / "last_run_stderr.log").open("w", encoding="utf-8")
    subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=err,
                     creationflags=flags, start_new_session=os.name != "nt")


def progress_panel(paths: Paths) -> None:
    status = read_status(paths)
    running = is_running(paths, status)

    @st.fragment(run_every=3 if running else None)
    def panel():
        stt = read_status(paths)
        log = paths.audit / "last_run.log"
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-14:]) if log.exists() else ""
        if is_running(paths, stt):
            n = len(stt.get("tickers", []))
            st.info(f"⏳ Spracovanie beží (počet firiem: {n}) – {stt.get('step', '')}")
            st.code(tail or "…", language=None)
        elif stt.get("state") == "running":
            st.warning("Posledný beh sa pravdepodobne prerušil (dlho bez aktivity). Spusti ho znova.")
            st.code(tail, language=None)
        elif stt.get("state") == "done":
            st.success(f"Posledný beh dokončený {stt.get('updated', '')[:16].replace('T', ' ')} – "
                       f"presnosť {stt.get('accuracy')} %")
            if st.session_state.pop("watching", False):
                st.cache_data.clear()
                st.rerun(scope="app")
        elif stt.get("state") == "error":
            st.error(f"Beh skončil chybou: {stt.get('error')}")
            st.code(tail, language=None)
        err = paths.audit / "last_run_stderr.log"
        if err.exists() and err.stat().st_size and stt.get("state") != "done" and not is_running(paths, stt):
            with st.expander("Chybový výstup procesu"):
                st.code(err.read_text(encoding="utf-8", errors="replace")[-3000:], language=None)

    panel()


# ---------- bočný panel ----------
st.sidebar.title("Finančné ukazovatele")
paths = Paths(ROOT)
# Verejná verzia (napr. Streamlit Community Cloud) nemá .env so SEC_USER_AGENT → len prezeranie výsledkov
PUBLIC = not user_agent()
raw = read(paths.kpis)
df = prepare(raw) if raw is not None and not raw.empty else None

selected: list[str] = []
if df is not None:
    sector = st.sidebar.selectbox("Odvetvie", sorted(df["sector"].unique()))
    dsec = df[df["sector"] == sector]
    names = dsec.drop_duplicates("ticker").set_index("ticker")["company"].to_dict()
    sector_tickers = sorted(names)
    selected = st.sidebar.multiselect("Spoločnosti (max. 8)", sector_tickers, default=sector_tickers[:8],
                                      max_selections=8, format_func=lambda t: f"{t} – {names[t]}")
    granularity = st.sidebar.radio("Obdobia", ["Štvrťroky", "Roky"], horizontal=True)
    years = sorted(dsec["fiscal_year"].unique())
    year_range = st.sidebar.select_slider("Fiškálne roky", options=years, value=(years[0], years[-1])) \
        if len(years) > 1 else (years[0], years[0])
    view = dsec[dsec["ticker"].isin(selected) & dsec["fiscal_year"].between(*year_range)]
    view = view[view["period"] == "FY"] if granularity == "Roky" else view[view["period"] != "FY"]
    # stabilné farby: firma má rovnakú farbu bez ohľadu na filter
    colors = color_scale(sector_tickers if len(sector_tickers) <= 8 else selected)
    st.sidebar.caption("Hodnoty v mil. USD, ak nie je uvedené inak. Fiškálne roky podľa firmy.")
    cur_all = read(paths.output / "valuation_current.csv")
    cur = cur_all[cur_all["sector"] == sector] if cur_all is not None and not cur_all.empty else None

st.title("Finančné ukazovatele z výkazov SEC")
tab_names = ["Prehľad", "Ocenenie", "Porovnanie", "Vývoj", "Tabuľka", "Kvalita dát"]
tabs = st.tabs(tab_names if PUBLIC else tab_names + ["Spracovať firmy"])
if PUBLIC:
    st.sidebar.caption("Verejná ukážka výsledkov. Spracovanie nových firiem beží v lokálnej inštalácii projektu.")

if df is None:
    for t in tabs[:6]:
        t.info("Zatiaľ nie sú spracované žiadne dáta. Spusti spracovanie firiem "
               "(karta **Spracovať firmy** alebo príkaz `python main.py run --all`).")
elif not selected or view.empty:
    for t in tabs[:6]:
        t.warning("Vyber aspoň jednu spoločnosť a obdobie v bočnom paneli.")
else:
    # ---------- Prehľad ----------
    with tabs[0]:
        t = st.selectbox("Spoločnosť", selected, format_func=lambda x: f"{x} – {names[x]}")
        rows = view[view["ticker"] == t].sort_values("period_key")
        last = rows.iloc[-1]
        prev = dsec[(dsec["ticker"] == t) & (dsec["fiscal_year"] == last["fiscal_year"] - 1)
                    & (dsec["period"] == last["period"])]
        prev = prev.iloc[0] if not prev.empty else None
        st.subheader(f"{names[t]} · {last['period_label']} (do {last['period_end']})")
        if last["data_check"] != "OK":
            st.warning(f"Kontrola kvality: {last['data_check']}")

        def delta(col: str, pct: bool):
            if prev is None or pd.isna(last[col]) or pd.isna(prev[col]):
                return None
            if pct and prev[col] != 0:
                return f"{100 * (last[col] - prev[col]) / abs(prev[col]):+.1f} % r/r"
            return f"{last[col] - prev[col]:+.1f} p. b. r/r" if KPI_INFO[col][1] == "%" else \
                   f"{last[col] - prev[col]:+.2f} r/r"

        cards = [("revenue_musd", True, "normal"), ("net_income_musd", True, "normal"),
                 ("net_margin_pct", False, "normal"), ("eps_diluted", True, "normal"),
                 ("free_cash_flow_musd", True, "normal"), ("shareholder_returns_musd", True, "normal"),
                 ("net_debt_to_equity", False, "inverse"), ("roe_pct", False, "normal")]
        cols = st.columns(4)
        for i, (c, pct, dc) in enumerate(cards):
            cols[i % 4].metric(KPI_INFO[c][0], fmt(c, last[c]), delta(c, pct), delta_color=dc,
                               help=KPI_INFO[c][3])
        st.caption("Zmena r/r = oproti rovnakému obdobiu predchádzajúceho fiškálneho roka.")

        if cur is not None and t in set(cur["ticker"]):
            v = cur.set_index("ticker").loc[t]
            st.markdown(f"**Aktuálne ocenenie** · cena {fmt('price_usd', v['price_usd'])} k {v['price_date']}, "
                        f"výsledky za posledné 4 štvrťroky do {v['basis']}")
            vcols = st.columns(4)
            for i, c in enumerate(["pe_ttm", "ev_ebitda_ttm", "fcf_yield_pct", "dividend_yield_pct"]):
                med = cur[c].median()
                vcols[i].metric(KPI_INFO[c][0], fmt(c, v[c]), help=KPI_INFO[c][3])
                vcols[i].caption(f"medián odvetvia: {fmt(c, med)}")
        show = pd.DataFrame({r["period_label"]: [num(c, r[c]) for c in KPI_INFO] for _, r in rows.iterrows()},
                            index=[label(c) for c in KPI_INFO])
        st.dataframe(show, width="stretch")

    # ---------- Ocenenie ----------
    with tabs[1]:
        if cur is None or cur.empty:
            st.info("Ocenenie zatiaľ nie je k dispozícii – chýbajú ceny akcií. Na karte **Spracovať firmy** "
                    "klikni na „Aktualizovať ceny akcií“ (alebo doplň catalog/manual_prices.csv).")
        else:
            st.markdown("Aktuálna cena akcie oproti výsledkom za **posledné 4 štvrťroky (TTM)**. "
                        "Pri P/E, EV/EBITDA a P/B znamená nižšia hodnota lacnejšiu akciu, pri výnosoch "
                        "vyššia hodnota viac hotovosti na každý investovaný dolár.")
            vsel = cur[cur["ticker"].isin(selected)]
            med = cur[VALUATION_COLS].median(numeric_only=True)
            ratio_cols = [c for c in VALUATION_COLS if c not in ("price_usd", "market_cap_musd")]
            disp = [{"Spoločnosť": r["company"], "Ticker": r["ticker"], "Cena k": r["price_date"],
                     "Výkazy do": r["basis"], **{label(c): num(c, r[c]) for c in VALUATION_COLS}}
                    for _, r in vsel.iterrows()]
            disp.append({"Spoločnosť": f"Medián odvetvia ({len(cur)} firiem)", "Ticker": "", "Cena k": "",
                         "Výkazy do": "", **{label(c): (num(c, med[c]) if c in ratio_cols else "")
                                              for c in VALUATION_COLS}})
            st.dataframe(pd.DataFrame(disp), hide_index=True, width="stretch")

            mult = st.selectbox("Porovnať", ["pe_ttm", "ev_ebitda_ttm", "pb", "fcf_yield_pct",
                                             "dividend_yield_pct", "shareholder_yield_pct"],
                                format_func=label, key="val_kpi")
            data = vsel[["ticker", "company", mult]].dropna()
            if not data.empty:
                base = alt.Chart(data).encode(
                    y=alt.Y("ticker:N", sort="x" if KPI_INFO[mult][1] == "x" else "-x", title=None),
                    x=alt.X(f"{mult}:Q", title=label(mult)),
                    tooltip=[alt.Tooltip("company:N", title="Spoločnosť"),
                             alt.Tooltip(f"{mult}:Q", title=KPI_INFO[mult][0], format=d3fmt(mult))])
                bars = base.mark_bar(color=PALETTE[0], cornerRadiusEnd=4, height={"band": 0.6})
                text = base.mark_text(align="left", dx=4, color="gray").encode(
                    text=alt.Text(f"{mult}:Q", format=d3fmt(mult)))
                rule = alt.Chart(pd.DataFrame({"m": [med[mult]]})).mark_rule(
                    strokeDash=[4, 4], color="gray").encode(x="m:Q")
                rule_txt = alt.Chart(pd.DataFrame({"m": [med[mult]], "t": ["medián odvetvia"]})).mark_text(
                    align="left", dx=4, dy=-6, color="gray", fontSize=11).encode(x="m:Q", y=alt.value(0), text="t:N")
                st.altair_chart((bars + text + rule + rule_txt).properties(height=max(160, 44 * len(data))),
                                width="stretch")
                st.caption(KPI_INFO[mult][3])
        st.caption(DISCLAIMER)

    # ---------- Porovnanie ----------
    with tabs[2]:
        c1, c2 = st.columns([2, 1])
        kpi = c1.selectbox("Ukazovateľ", list(KPI_INFO), format_func=label, key="cmp_kpi")
        periods = view.drop_duplicates("period_key").sort_values("period_key")["period_label"].tolist()
        per = c2.selectbox("Obdobie", periods[::-1])
        data = view[view["period_label"] == per][["ticker", "company", kpi]].dropna()
        if data.empty:
            st.info("Pre toto obdobie nie sú dáta.")
        else:
            base = alt.Chart(data).encode(
                y=alt.Y("ticker:N", sort="-x", title=None),
                x=alt.X(f"{kpi}:Q", title=label(kpi)),
                tooltip=[alt.Tooltip("company:N", title="Spoločnosť"),
                         alt.Tooltip(f"{kpi}:Q", title=KPI_INFO[kpi][0], format=d3fmt(kpi))])
            bars = base.mark_bar(color=PALETTE[0], cornerRadiusEnd=4, height={"band": 0.6})
            text = base.mark_text(align="left", dx=4, color="gray").encode(
                text=alt.Text(f"{kpi}:Q", format=d3fmt(kpi)))
            st.altair_chart((bars + text).properties(height=max(160, 44 * len(data)),
                                                     title=f"{KPI_INFO[kpi][0]} · {per}"),
                            width="stretch")
            st.caption(KPI_INFO[kpi][3])

    # ---------- Vývoj ----------
    with tabs[3]:
        kpi = st.selectbox("Ukazovateľ", list(KPI_INFO), format_func=label, key="trend_kpi")
        data = view[["ticker", "company", "period_label", "period_key", kpi]].dropna()
        order = data.sort_values("period_key")["period_label"].unique().tolist()
        enc = dict(x=alt.X("period_label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                   y=alt.Y(f"{kpi}:Q", title=label(kpi)),
                   color=alt.Color("ticker:N", scale=colors, title="Spoločnosť"))
        tip = [alt.Tooltip("company:N", title="Spoločnosť"), alt.Tooltip("period_label:N", title="Obdobie"),
               alt.Tooltip(f"{kpi}:Q", title=KPI_INFO[kpi][0], format=d3fmt(kpi))]
        lines = alt.Chart(data).mark_line(strokeWidth=2).encode(**enc)
        points = alt.Chart(data).mark_point(filled=True, size=70).encode(**enc, tooltip=tip)
        chart = lines + points
        if data["ticker"].nunique() <= 4:  # priame popisky na konci čiar
            ends = data.sort_values("period_key").groupby("ticker").tail(1)
            chart += alt.Chart(ends).mark_text(align="left", dx=8, fontWeight="bold").encode(
                x=enc["x"], y=enc["y"], text="ticker:N", color=alt.Color("ticker:N", scale=colors, legend=None))
        st.altair_chart(chart.properties(height=420), width="stretch")
        st.caption(KPI_INFO[kpi][3])

    # ---------- Tabuľka ----------
    with tabs[4]:
        table = view[["company", "ticker", "period_label", "period_end"] + list(KPI_INFO) + ["data_check"]]
        cfg = {"company": "Spoločnosť", "ticker": "Ticker", "period_label": "Obdobie", "period_end": "Koniec obdobia",
               "data_check": "Kontrola kvality"}
        for c, (name, unit, _, desc) in KPI_INFO.items():
            f = "%,.0f" if unit == "mil. USD" else "%.1f %%" if unit == "%" else "%.2f"
            cfg[c] = st.column_config.NumberColumn(f"{name} ({unit})", help=desc, format=f)
        st.dataframe(table, column_config=cfg, hide_index=True, width="stretch")
        st.download_button("Stiahnuť CSV (filtrované)", table.to_csv(index=False).encode("utf-8-sig"),
                           file_name="investor_kpis_filtered.csv", mime="text/csv")

    # ---------- Kvalita dát ----------
    with tabs[5]:
        st.markdown("Každá hodnota z NLP modelu sa porovná s oficiálnou XBRL hodnotou zo SEC. "
                    "Presnosť sa meria na firmách, ktoré model pri tréningu **nevidel**.")
        runs, acc_m = read(paths.audit / "runs.csv"), read(paths.audit / "accuracy_by_metric.csv")
        acc_c = read(paths.audit / "accuracy_by_company.csv")
        c1, c2, c3 = st.columns(3)
        if runs is not None:
            c1.metric("Presnosť posledného behu", f"{runs.iloc[-1]['accuracy_pct']:.1f} %")
            c2.metric("Spracované dokumenty", int(runs.iloc[-1]["documents"]))
        c3.metric("Obdobia s upozornením", int((view["data_check"] != "OK").sum()))
        a, b = st.columns(2)
        if acc_m is not None:
            a.markdown("**Presnosť podľa metriky**")
            a.dataframe(acc_m, hide_index=True, width="stretch")
        if acc_c is not None:
            b.markdown("**Presnosť podľa spoločnosti**")
            b.dataframe(acc_c[acc_c["ticker"].isin(selected)], hide_index=True, width="stretch")
        flagged = view[view["data_check"] != "OK"][["ticker", "period_label", "data_check"]]
        st.markdown("**Obdobia na kontrolu**")
        if flagged.empty:
            st.success("Všetky zobrazené obdobia sedia s oficiálnymi XBRL hodnotami.")
        else:
            st.dataframe(flagged, hide_index=True, width="stretch")
        ex = read(paths.audit / "extracted_values.csv")
        if ex is not None:
            with st.expander("Detail extrakcie – z ktorého riadku výkazu model čítal"):
                d = ex[ex["ticker"].isin(selected)][["ticker", "fiscal_year", "fiscal_quarter", "metric",
                                                     "value", "gold_value", "confidence", "source_row", "match"]]
                st.dataframe(d.sort_values("confidence"), hide_index=True, width="stretch")

# ---------- Spracovať firmy ----------
def processing_tab():
    cat = load_catalog()
    status = read_status(paths)
    running = is_running(paths, status)
    all_label = "Všetky odvetvia (celý katalóg)"
    c1, c2 = st.columns([1, 2])
    sec = c1.selectbox("Odvetvie", sectors(cat) + [all_label], key="proc_sector")
    options = cat if sec == all_label else companies_in(sec, cat)
    opt_names = dict(zip(options["ticker"], options["name"]))
    picks = c2.multiselect("Spoločnosti", list(opt_names), default=list(opt_names),
                           format_func=lambda t: f"{t} – {opt_names[t]}", key=f"picks_{sec}")
    this_year = date.today().year
    yrs = st.multiselect("Fiškálne roky", list(range(this_year - 6, this_year + 1)), default=DEFAULT_YEARS)
    st.caption("Spracovanie beží na pozadí – medzitým môžeš v aplikácii pokojne klikať, prípadne ju aj zavrieť. "
               "Model sa učí zo všetkých doteraz stiahnutých výkazov, takže každé nové odvetvie ho zlepšuje. "
               "Banky a poisťovne majú iné výkazy – sledované ukazovatele na ne nesedia.")
    if not user_agent():
        st.error('Chýba SEC_USER_AGENT v súbore .env (napr. SEC_USER_AGENT="Meno Priezvisko meno@domena.cz").')
    if st.button("Stiahnuť a spracovať", type="primary",
                 disabled=running or not (picks and yrs and user_agent())):
        start_background(paths, picks, sorted(yrs))
        st.session_state["watching"] = True
        st.rerun()
    progress_panel(paths)

    if st.button("Aktualizovať ceny akcií", help="Stiahne aktuálne ceny z Yahoo Finance a prepočíta ocenenie"):
        from src.valuation import refresh_valuation
        with st.status("Sťahujem ceny…", expanded=True) as status:
            refresh_valuation(paths, log=st.write)
            status.update(label="Ceny aktualizované", state="complete")
        st.cache_data.clear()

    with st.expander("Pridať spoločnosť do katalógu"):
        a1, a2, a3 = st.columns(3)
        new_t = a1.text_input("Ticker (USA, podáva 10-K/10-Q)")
        new_s = a2.selectbox("Odvetvie", sectors(cat) + ["➕ Nové odvetvie…"])
        if new_s.startswith("➕"):
            new_s = a2.text_input("Názov nového odvetvia")
        new_n = a3.text_input("Názov spoločnosti")
        new_c = st.text_input("CIK (nepovinné)", help="Len ak firma zmenila právnu štruktúru – napr. "
                              "'2115436;34088' (nový holding; pôvodný emitent). Inak sa CIK dohľadá automaticky.")
        if st.button("Pridať") and new_t and new_s:
            add_company(new_t, new_s, "", new_n, new_c)
            st.success(f"{new_t.upper()} pridaná do odvetvia {new_s}.")
            st.rerun()


if not PUBLIC:
    with tabs[6]:
        processing_tab()
