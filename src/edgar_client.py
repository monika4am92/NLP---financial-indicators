"""Sťahovanie 10-Q / 10-K podaní zo SEC EDGAR (oficiálne bezplatné API)."""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Callable

import requests

from .catalog import catalog_ciks, load_catalog, ticker_map
from .config import Paths

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"


def _anchor(report_date: date) -> date:
    # 52/53-týždňové roky končia napr. 27.9. alebo 1.10. → posun o týždeň späť
    return report_date - timedelta(days=7)


def fiscal_quarter(report_date: date, fye_month: int) -> int:
    """1-4 podľa mesiaca konca obdobia vzhľadom na koniec fiškálneho roka."""
    return ((_anchor(report_date).month - fye_month - 1) % 12) // 3 + 1


def fiscal_year(report_date: date, fye_month: int) -> int:
    d = _anchor(report_date)
    return d.year if d.month <= fye_month else d.year + 1


class EdgarClient:
    def __init__(self, user_agent: str, pause: float = 0.15, log: Callable = print):
        if not user_agent or "@" not in user_agent:
            raise RuntimeError(
                "Chýba SEC_USER_AGENT. SEC vyžaduje identifikáciu – doplň do súboru .env riadok:\n"
                'SEC_USER_AGENT="Meno Priezvisko meno@domena.cz"')
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self.pause = pause  # SEC limit: max 10 požiadaviek/s
        self.log = log

    def _get(self, url: str) -> requests.Response:
        for attempt in range(4):
            r = self.s.get(url, timeout=60)
            time.sleep(self.pause)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
        r.raise_for_status()
        return r

    def get_json(self, url: str) -> dict:
        return self._get(url).json()

    def company_filings(self, cik: int) -> tuple[dict, list[dict]]:
        sub = self.get_json(SUBMISSIONS_URL.format(cik=cik))
        tables = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files", []):  # staršie podania sú na ďalších stranách
            tables.append(self.get_json(SUBMISSIONS_PAGE_URL.format(name=f["name"])))
        return sub, tables

    @staticmethod
    def select_filings(tables: list[dict], cik: int, years: list[int], fye_month: int) -> list[dict]:
        out = []
        for t in tables:
            for form, acc, rdate, fdate, doc in zip(t["form"], t["accessionNumber"], t["reportDate"],
                                                     t["filingDate"], t["primaryDocument"]):
                if form not in ("10-Q", "10-K") or not rdate:
                    continue
                rd = date.fromisoformat(rdate)
                fy, fq = fiscal_year(rd, fye_month), fiscal_quarter(rd, fye_month)
                if fy not in years or (form == "10-K") != (fq == 4):
                    continue
                out.append({"form": form, "accession": acc, "report_date": rdate, "filing_date": fdate,
                            "fiscal_year": fy, "fiscal_quarter": fq,
                            "url": ARCHIVE_URL.format(cik=cik, acc_nodash=acc.replace("-", ""), doc=doc)})
        best: dict[tuple, dict] = {}  # pre každý štvrťrok najnovšie podanie
        for f in sorted(out, key=lambda x: x["filing_date"]):
            best[(f["fiscal_year"], f["fiscal_quarter"])] = f
        return [best[k] for k in sorted(best)]

    def download(self, paths: Paths, tickers: list[str], years: list[int]) -> list[dict]:
        catalog = load_catalog().set_index("ticker")
        tmap = ticker_map(self, paths.raw / "company_tickers.json")
        new_docs = []
        for ticker in tickers:
            ciks = catalog_ciks(ticker, catalog.reset_index())
            if not ciks and ticker not in tmap:
                self.log(f"[{ticker}] ticker sa v SEC nenašiel – preskakujem")
                continue
            if not ciks:
                ciks = [tmap[ticker]["cik"]]
            filings, name, sector, fye_month = [], "", "", 12
            for i, cik in enumerate(ciks):
                sub, tables = self.company_filings(cik)
                fye = sub.get("fiscalYearEnd") or "1231"
                if i == 0:  # aktuálny emitent určuje názov, odvetvie a fiškálny rok
                    fye_month = int(fye[:2])
                    name = sub.get("name") or tmap.get(ticker, {}).get("title", ticker)
                    sector = catalog.loc[ticker, "sector"] if ticker in catalog.index else (
                        sub.get("sicDescription") or "Iné")
                    self.log(f"[{ticker}] {name} – koniec fiškálneho roka {fye[2:]}.{fye[:2]}.")
                else:
                    self.log(f"  + predchádzajúci emitent {sub.get('name')} (CIK {cik})")
                for f in self.select_filings(tables, cik, years, fye_month):
                    filings.append({**f, "cik": cik, "filer_name": sub.get("name") or name})
            best: dict[tuple, dict] = {}  # ak podali obaja emitenti, platí novší výkaz
            for f in sorted(filings, key=lambda x: x["filing_date"]):
                best[(f["fiscal_year"], f["fiscal_quarter"])] = f
            filings = [best[k] for k in sorted(best)]
            if not filings:
                self.log(f"  ! [{ticker}] pre roky {years} sa nenašli žiadne 10-Q/10-K podania. Ak firma zmenila "
                         f"právnu štruktúru, doplň v catalog/companies.csv do stĺpca cik aj pôvodný CIK "
                         f"(python main.py diagnose {ticker}).")
            for f in filings:
                target = paths.raw / ticker / f"{f['accession']}.htm"
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and not looks_valid(target.read_bytes()):
                    target.unlink()  # poškodený/neúplný súbor z predchádzajúceho behu
                if not target.exists():
                    self.log(f"  ↓ FY{f['fiscal_year']} Q{f['fiscal_quarter']} {f['form']} ({f['report_date']})")
                    content = self._get(f["url"]).content
                    if not looks_valid(content):
                        time.sleep(3)
                        content = self._get(f["url"]).content
                    if not looks_valid(content):
                        self.log(f"  ! [{ticker}] {f['url']} nevyzerá ako výkaz ({len(content):,} B) – preskakujem")
                        continue
                    target.write_bytes(content)
                new_docs.append({**f, "ticker": ticker, "company": name, "sector": sector,
                                 "fye_month": fye_month, "path": str(target.relative_to(paths.base))})
        return update_manifest(paths, new_docs)


def looks_valid(content: bytes) -> bool:
    """Skutočný 10-Q/10-K má stovky kB a tabuľky; chybová stránka SEC nie."""
    head = content[:20_000].lower()
    blocked = b"request rate threshold" in head or b"undeclared automated tool" in head
    return len(content) > 15_000 and (b"<table" in content or b"<TABLE" in content) and not blocked


def update_manifest(paths: Paths, docs: list[dict]) -> list[dict]:
    """Manifest sa priebežne dopĺňa – model sa učí zo všetkých kedy stiahnutých podaní."""
    existing = json.loads(paths.manifest.read_text(encoding="utf-8")) if paths.manifest.exists() else []
    by_acc = {d["accession"]: d for d in existing}
    by_acc.update({d["accession"]: d for d in docs})
    manifest = sorted(by_acc.values(), key=lambda d: (d["ticker"], d["fiscal_year"], d["fiscal_quarter"]))
    paths.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return docs
