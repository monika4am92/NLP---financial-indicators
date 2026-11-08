"""Celý beh: stiahnutie → dataset → vyhodnotenie → finálny model → investorská tabuľka.
Volá sa z príkazového riadku (main.py); aplikácia (app.py) ho spúšťa ako samostatný proces,
aby ho kliknutie v prehliadači neprerušilo. Priebeh sa zapisuje do output/audit/status.json
a output/audit/last_run.log."""
from __future__ import annotations

import json
import traceback
from datetime import datetime
from typing import Callable

import joblib
import pandas as pd

from .config import Paths, user_agent
from .dataset import build_dataset
from .evaluate import accuracy_table, leave_one_company_out, overall_accuracy
from .kpi import build_investor_table, upsert
from .model import train
from .valuation import refresh_valuation


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_status(paths: Paths) -> dict:
    f = paths.audit / "status.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_status(paths: Paths, **kw) -> None:
    status = {**read_status(paths), **kw, "updated": _now()}
    (paths.audit / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")


def run(paths: Paths, tickers: list[str], years: list[int], log: Callable = print,
        download: bool = True) -> dict:
    paths.ensure()
    logfile = (paths.audit / "last_run.log").open("w", encoding="utf-8")

    def tee(msg: str) -> None:
        log(msg)
        logfile.write(f"{msg}\n")
        logfile.flush()
        if msg.lstrip()[:1] in "①②③④⑤⑥":
            _write_status(paths, step=msg.strip())

    _write_status(paths, state="running", started=_now(), tickers=tickers, years=years, step="štart",
                  accuracy=None, error=None)
    try:
        result = _run(paths, [t.upper() for t in tickers], years, tee, download)
        _write_status(paths, state="done", step="Hotovo", accuracy=result["accuracy"])
        return result
    except BaseException as e:  # noqa: BLE001 – stav musí ostať zapísaný aj pri prerušení
        tee(traceback.format_exc())
        _write_status(paths, state="error", error=str(e) or e.__class__.__name__)
        raise
    finally:
        logfile.close()


def _run(paths: Paths, tickers: list[str], years: list[int], log: Callable, download: bool) -> dict:
    if download:
        from .edgar_client import EdgarClient
        log("① Sťahujem výkazy zo SEC EDGAR")
        docs = EdgarClient(user_agent(), log=log).download(paths, tickers, years)
        missing = sorted(set(tickers) - {d["ticker"] for d in docs})
        if missing:
            log(f"  ! bez stiahnutých výkazov: {', '.join(missing)} (podrobnosti: python main.py diagnose TICKER)")
        tickers = sorted({d["ticker"] for d in docs})
        if not tickers:
            raise RuntimeError("Pre vybrané firmy a roky sa nenašli žiadne 10-Q/10-K podania.")

    log("② Spracúvam dokumenty a vytváram trénovacie dáta")
    rows, gold = build_dataset(paths, log)

    log("③ Vyhodnotenie: model číta každú firmu bez toho, aby ju videl pri tréningu")
    ex, report = leave_one_company_out(rows, gold, tickers, log)
    acc = overall_accuracy(ex)
    log(f"   Presnosť extrakcie na nevidených firmách: {acc} %")
    keys = ["ticker", "fiscal_year"]
    upsert(paths.audit / "extracted_values.csv", ex, keys)
    by_metric, by_company = accuracy_table(ex, "metric"), accuracy_table(ex, "ticker")
    by_metric.to_csv(paths.audit / "accuracy_by_metric.csv")
    upsert(paths.audit / "accuracy_by_company.csv", by_company.reset_index(), ["ticker"])
    (paths.audit / "evaluation_report.txt").write_text(
        f"Presnosť hodnôt (leave-one-company-out): {acc} %\n\nPodľa metriky:\n{by_metric.to_string()}\n\n"
        f"Podľa spoločnosti:\n{by_company.to_string()}\n\nKlasifikácia riadkov:\n{report}", encoding="utf-8")

    log("④ Trénujem finálny model na všetkých dokumentoch")
    joblib.dump(train(rows), paths.models / "row_classifier.joblib")

    log("⑤ Počítam ukazovatele pre investorov")
    investor, reference, base = build_investor_table(ex, gold)
    upsert(paths.kpis, investor, keys)
    upsert(paths.audit / "kpi_xbrl_reference.csv", reference, keys)
    upsert(paths.audit / "valuation_base.csv", base, keys)

    log("⑥ Ocenenie: ceny akcií a P/E, EV/EBITDA, výnosy")
    try:
        refresh_valuation(paths, log, fetch=download)
    except Exception as e:  # noqa: BLE001 – ocenenie nesmie zhodiť celý beh
        log(f"  ! ocenenie sa nepodarilo ({e}) – skús neskôr: python main.py prices")

    run_row = pd.DataFrame([{"run_at": _now(), "tickers": " ".join(tickers), "years": " ".join(map(str, years)),
                             "accuracy_pct": acc, "documents": int(ex.doc_id.nunique())}])
    runs = paths.audit / "runs.csv"
    run_row.to_csv(runs, mode="a", header=not runs.exists(), index=False, encoding="utf-8")
    log(f"Hotovo – presnosť {acc} % → {paths.kpis}")
    return {"accuracy": acc, "tickers": tickers, "rows": len(investor)}
