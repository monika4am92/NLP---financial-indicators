"""Experimentálne: použitie natrénovaného modelu na PDF výročnú správu
(napr. firmy mimo SEC – Petrobras, KEPCO, PetroChina v angl. verzii).

PDF nemá XBRL značky, takže tu sa ukazuje hlavný prínos NLP modelu:
čísla hľadá iba podľa textu riadku a kontextu stránky.
"""
from __future__ import annotations

import re

import pandas as pd

from .html_parser import clean_label, detect_periods, detect_scale, parse_values_ext, statement_type

_LINE = re.compile(r"^(?P<label>[A-Za-z][^\d$()]*?)\s+(?P<nums>[\s$()\-—–,.\d]+)$")


def rows_from_pdf(path: str, form: str = "10-K", ticker: str = "PDF", report_date: str = "") -> pd.DataFrame:
    import pdfplumber

    from .model import row_tokens

    records = []
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            header = " ".join(lines[:6])
            scale = detect_scale(header, text[:1500])
            context = f"form_{form.replace('-', '').lower()} {header}".lower()[-450:]
            periods, stmt = detect_periods(header), statement_type(header.lower())
            parsed = []
            for li, line in enumerate(lines):
                m = _LINE.match(line)
                if m:
                    vals, decs = parse_values_ext(m.group("nums").split())
                    parsed.append((li, clean_label(m.group("label")), vals, decs))
                elif re.search(r"[A-Za-z]{3,}", line) and not re.search(r"\d", line):
                    parsed.append((li, clean_label(line), [], []))
            section = ""
            for i, (li, label, vals, decs) in enumerate(parsed):
                if not vals:
                    section = label
                    continue
                prev_l = parsed[i - 1][1] if i > 0 else ""
                next_l = parsed[i + 1][1] if i + 1 < len(parsed) else ""
                records.append({"doc_id": f"{ticker}_{form}_{report_date or path}", "ticker": ticker,
                                "company": ticker, "sector": "", "fiscal_year": report_date[:4],
                                "form": form, "fiscal_quarter": 4 if form == "10-K" else 0,
                                "report_date": report_date, "table_idx": pi, "row_idx": li,
                                "label_text": label, "context": context,
                                "row_ctx": row_tokens(section, prev_l, next_l, stmt, "none", periods, vals[0], decs[0]),
                                "scale": scale, "values": vals, "decimals": decs, "periods": periods, "entity": "none",
                                "stmt": stmt, "value0": vals[0], "n_values": len(vals), "target": "UNKNOWN"})
    return pd.DataFrame(records)
