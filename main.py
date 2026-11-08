from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src import config
from src.catalog import add_company, companies_in, load_catalog, sectors
from src.config import DEFAULT_YEARS, Paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["sectors", "run", "add", "prices", "kpi", "diagnose", "explain", "remove", "pdf"])
    ap.add_argument("arg", nargs="?", help="ticker (add) alebo PDF súbor (pdf)")
    ap.add_argument("--sector", help="odvetvie z katalógu")
    ap.add_argument("--tickers", nargs="*", default=[])
    ap.add_argument("--all", action="store_true", help="všetky firmy z katalógu")
    ap.add_argument("--years", nargs="*", type=int, default=DEFAULT_YEARS)
    ap.add_argument("--name", default="")
    ap.add_argument("--subsector", default="")
    ap.add_argument("--ticker", default="PDF")
    ap.add_argument("--form", default="10-K")
    ap.add_argument("--report-date", default="")
    ap.add_argument("--year", type=int, help="fiškálny rok (explain)")
    ap.add_argument("--q", type=int, help="štvrťrok 1–4, 4 = 10-K (explain)")
    ap.add_argument("--metric", help="metrika (explain), napr. net_income")
    ap.add_argument("--workdir", default=None, help="default: koreň projektu")
    a = ap.parse_args()

    base = Path(a.workdir) if a.workdir else config.ROOT
    paths = Paths(base).ensure()

    if a.command == "sectors":
        cat = load_catalog()
        for s in sectors(cat):
            print(f"\n{s}")
            for _, r in companies_in(s, cat).iterrows():
                print(f"  {r.ticker:6} {r['name']}  ({r.subsector})")

    elif a.command == "add":
        if not a.arg or not a.sector:
            sys.exit("Použitie: python main.py add TICKER --sector \"Odvetvie\" [--name \"Názov\"]")
        add_company(a.arg, a.sector, a.subsector, a.name)
        print(f"{a.arg.upper()} pridaná do odvetvia {a.sector}")

    elif a.command == "run":
        from src.pipeline import run
        tickers = list(a.tickers)
        if a.sector:
            tickers += list(companies_in(a.sector)["ticker"])
        if a.all:
            tickers += list(load_catalog()["ticker"])
        if not tickers:
            sys.exit("Zadaj --sector, --tickers alebo --all (zoznam: python main.py sectors)")
        run(paths, sorted(set(t.upper() for t in tickers)), a.years)

    elif a.command == "prices":
        from src.valuation import refresh_valuation
        cur = refresh_valuation(paths)
        if not cur.empty:
            print(cur[["ticker", "price_date", "price_usd", "pe_ttm", "ev_ebitda_ttm", "fcf_yield_pct",
                       "dividend_yield_pct"]].to_string(index=False))

    elif a.command == "diagnose":
        diagnose(paths, (a.arg or "").upper(), a.years)

    elif a.command == "kpi":
        recompute_kpis(paths)

    elif a.command == "remove":
        remove(paths, a.sector, [t.upper() for t in a.tickers])

    elif a.command == "explain":
        explain(paths, (a.arg or "").upper(), a.year, a.q, a.metric)

    elif a.command == "pdf":
        import joblib
        from src.model import extract
        from src.pdf_reader import rows_from_pdf
        model = joblib.load(paths.models / "row_classifier.joblib")
        rows = rows_from_pdf(a.arg, form=a.form, ticker=a.ticker, report_date=a.report_date)
        if rows.empty:
            sys.exit("V PDF sa nenašli riadky s číslami (skenované PDF treba najprv OCR).")
        res = extract(model, rows)
        out = paths.audit / f"pdf_extract_{a.ticker}.csv"
        res.to_csv(out, index=False, encoding="utf-8-sig")
        print(res[["metric", "value", "confidence", "source_row"]].to_string(index=False))
        print(f"→ {out}")


def recompute_kpis(paths: Paths) -> None:
    """Prepočíta investorské ukazovatele a ocenenie z už extrahovaných hodnôt (bez sťahovania a tréningu)."""
    import pandas as pd

    from src.kpi import build_investor_table
    from src.valuation import refresh_valuation
    src_file = paths.audit / "extracted_values.csv"
    if not src_file.exists():
        sys.exit("Chýba output/audit/extracted_values.csv – najprv spusti: python main.py run --all")
    ex = pd.read_csv(src_file)
    gold = ex[["doc_id", "metric", "gold_value"]].dropna()
    investor, reference, base = build_investor_table(ex, gold)
    investor.to_csv(paths.kpis, index=False, encoding="utf-8-sig")
    reference.to_csv(paths.audit / "kpi_xbrl_reference.csv", index=False, encoding="utf-8-sig")
    base.to_csv(paths.audit / "valuation_base.csv", index=False, encoding="utf-8-sig")
    refresh_valuation(paths, fetch=False)
    print(f"Ukazovatele prepočítané → {paths.kpis}")


def remove(paths: Paths, sector: str | None, tickers: list[str]) -> None:
    """Odstráni firmy z katalógu, z tréningových dát (manifest) aj zo všetkých výstupov."""
    import json

    import pandas as pd

    from src.config import CATALOG_PATH
    targets = set(tickers)
    if sector:
        cat = load_catalog()
        targets |= set(cat[cat["sector"] == sector]["ticker"])
        if paths.kpis.exists():
            k = pd.read_csv(paths.kpis)
            targets |= set(k[k["sector"] == sector]["ticker"])
    if not targets:
        sys.exit("Nenašli sa žiadne firmy na odstránenie (zadaj --sector alebo --tickers).")
    print("Odstraňujem:", ", ".join(sorted(targets)))
    cat = pd.read_csv(CATALOG_PATH, dtype=str).fillna("")
    cat[~cat["ticker"].str.upper().isin(targets)].to_csv(CATALOG_PATH, index=False)
    if paths.manifest.exists():
        man = json.loads(paths.manifest.read_text(encoding="utf-8"))
        man = [d for d in man if d["ticker"] not in targets]
        paths.manifest.write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    files = [paths.kpis, paths.output / "valuation_current.csv", paths.output / "market_prices.csv",
             paths.audit / "extracted_values.csv", paths.audit / "kpi_xbrl_reference.csv",
             paths.audit / "valuation_base.csv", paths.audit / "accuracy_by_company.csv"]
    for f in files:
        if f.exists():
            df = pd.read_csv(f)
            if "ticker" in df:
                df[~df["ticker"].isin(targets)].to_csv(f, index=False, encoding="utf-8-sig")
    print("Hotovo. Stiahnuté výkazy ostali v data/raw (nevadia). Spusti znova: python main.py run --all")


def explain(paths: Paths, ticker: str, year: int | None, q: int | None, metric: str | None) -> None:
    """Vypíše kandidátov, z ktorých model vyberal hodnotu – na ladenie chýb konkrétnej firmy."""
    import json

    import joblib
    import pandas as pd

    from src.config import METRICS
    from src.dataset import doc_id, process_doc
    from src.model import FEATURES, _pick_value, extract
    if not ticker:
        sys.exit("Použitie: python main.py explain TICKER --year 2025 --q 4 [--metric net_income]")
    docs = [d for d in json.loads(paths.manifest.read_text(encoding="utf-8")) if d["ticker"] == ticker
            and (year is None or d["fiscal_year"] == year) and (q is None or d["fiscal_quarter"] == q)]
    if not docs:
        sys.exit("Dokument sa nenašiel v manifeste.")
    model = joblib.load(paths.models / "row_classifier.joblib")
    metrics = [metric] if metric else list(METRICS)
    for d in docs[:1]:
        rows, gold = process_doc(paths, d)
        print(f"=== {doc_id(d)}  {d['form']}  {d['report_date']}  ({len(rows)} riadkov)")
        ents = rows.groupby(["table_idx"]).first()[["entity", "stmt"]]
        print(f"Tabuľky: entita {ents.entity.value_counts().to_dict()}, výkaz {ents.stmt.value_counts().to_dict()}")
        proba = model.predict_proba(rows[FEATURES])
        classes = list(model.classes_)
        chosen = extract(model, rows).set_index("metric")
        g = gold.set_index("metric")["gold_value"] if len(gold) else pd.Series(dtype=float)
        for m in metrics:
            if m not in classes:
                continue
            print(f"\n--- {m}: vybraté {chosen['value'].get(m)}  (správne podľa XBRL: {g.get(m)})")
            col = proba[:, classes.index(m)]
            for k in col.argsort()[::-1][:6]:
                r = rows.iloc[k]
                picked = _pick_value(r, METRICS[m])
                print(f"  p={col[k]:.2f} tab={r.table_idx} {r.stmt}/{r.entity} obd={list(r.periods)} "
                      f"hodnota={picked[0] if picked else 'nevyhovuje'}  '{r.label_text[:60]}'")
                print(f"        kontext: …{r.context[-110:]}")


def diagnose(paths: Paths, ticker: str, years: list[int]) -> None:
    """Vypíše, čo sa pre firmu stiahlo a spracovalo – pomôže zistiť, prečo chýba vo výsledkoch."""
    import json

    from src.dataset import doc_id, process_doc
    from src.edgar_client import looks_valid
    if not ticker:
        sys.exit("Použitie: python main.py diagnose TICKER")
    print(f"=== {ticker} ===")
    docs = [d for d in json.loads(paths.manifest.read_text(encoding="utf-8"))
            if d["ticker"] == ticker] if paths.manifest.exists() else []
    print(f"V manifeste: {len(docs)} dokumentov")
    for d in docs:
        f = paths.base / d["path"]
        size = f.stat().st_size if f.exists() else 0
        line = f"  {doc_id(d)} {d['form']} {d['report_date']}  {size / 1e6:.1f} MB"
        if not f.exists():
            print(line + "  ! súbor chýba")
            continue
        content = f.read_bytes()
        if not looks_valid(content):
            print(line + "  ! nevyzerá ako výkaz (chybová stránka SEC?) – zmaž súbor a spusti znova")
            continue
        rows, gold = process_doc(paths, d)
        print(line + f"  riadkov tabuliek: {len(rows)}, označených: {int((rows.target != 'OTHER').sum()) if len(rows) else 0},"
                     f" XBRL metrík: {len(gold)}")
    if docs:
        return
    print("Dokumenty sa nestiahli. Overujem v SEC…")
    from src.catalog import ticker_map
    from src.edgar_client import EdgarClient
    try:
        client = EdgarClient(config.user_agent())
        from src.catalog import catalog_ciks
        tmap = ticker_map(client, paths.raw / "company_tickers.json")
        ciks = catalog_ciks(ticker) or ([tmap[ticker]["cik"]] if ticker in tmap else [])
        if not ciks:
            print(f"  ! ticker {ticker} nie je v zozname SEC (company_tickers.json) ani v stĺpci cik katalógu")
            return
        print(f"  CIK: {', '.join(map(str, ciks))}" + ("  (z katalógu)" if catalog_ciks(ticker) else ""))
        for cik in ciks:
            sub, tables = client.company_filings(cik)
            fye = sub.get("fiscalYearEnd") or "1231"
            found = client.select_filings(tables, cik, years, int(fye[:2]))
            forms = {}
            for t in tables:
                for form in t["form"]:
                    forms[form] = forms.get(form, 0) + 1
            print(f"  {sub.get('name')} (CIK {cik}), koniec FY {fye}, podaní spolu {sum(forms.values())}, "
                  f"10-K: {forms.get('10-K', 0)}, 10-Q: {forms.get('10-Q', 0)}")
            print(f"    vybraté pre roky {years}: {len(found)}")
            for f in found:
                print(f"     FY{f['fiscal_year']} Q{f['fiscal_quarter']} {f['form']} {f['report_date']} {f['url']}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! chyba pri overovaní: {e}")


if __name__ == "__main__":
    main()
