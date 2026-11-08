"""Tvorba trénovacieho datasetu (weak supervision cez inline XBRL), s cache po dokumentoch."""
from __future__ import annotations

import json
from datetime import date
from typing import Callable

import pandas as pd

from .config import METRICS, Paths
from .html_parser import PARSER_VERSION, Context, ParsedFiling, choose_column, parse_filing, required_months

DOC_META = ["doc_id", "ticker", "company", "sector", "form", "fiscal_year", "fiscal_quarter", "report_date"]


def doc_id(d: dict) -> str:
    return f"{d['ticker']}_FY{d['fiscal_year']}Q{d['fiscal_quarter']}"


def period_matches(kind: str, ctx: Context | None, report_date: date, form: str, fq: int) -> bool:
    """Patrí XBRL kontext k obdobiu, ktoré pre danú metriku chceme (a k materskej firme)?"""
    if ctx is None or ctx.has_dims:
        return False
    if kind == "instant":
        return ctx.instant is not None and abs((ctx.instant - report_date).days) <= 5
    if ctx.start is None or ctx.end is None or abs((ctx.end - report_date).days) > 5:
        return False
    days = (ctx.end - ctx.start).days
    if form == "10-K":
        return 350 <= days <= 380
    if kind == "duration_q":
        return 80 <= days <= 100
    return abs(days - 91.3 * fq) <= 25  # duration_ytd (25 dní tolerancia pre 52/53-týždňové roky)


def _sign(spec: dict, v: float) -> float:
    return abs(v) if spec.get("outflow") or spec.get("positive") else v


def gold_values(p: ParsedFiling, report_date: date, form: str, fq: int) -> dict[str, tuple[str, float, list]]:
    """Referenčné hodnoty z XBRL: metric → (použitý koncept, hodnota, alternatívne prijateľné hodnoty)."""
    out = {}
    for metric, spec in METRICS.items():
        found = []
        for concept in spec["concepts"]:
            vals = [f.value for f in p.facts if f.concept == concept and
                    period_matches(spec["kind"], p.contexts.get(f.context_id), report_date, form, fq)]
            if vals:
                found.append((concept, _sign(spec, vals[0])))
        if not found:
            continue
        best = max(found, key=lambda x: abs(x[1])) if spec.get("gold") == "max" else found[0]
        alts = [v for _, v in found] if spec.get("accept_any") else [best[1]]
        out[metric] = (best[0], best[1], alts)
    return out


def process_doc(paths: Paths, doc: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    from .model import row_tokens
    did = doc_id(doc)
    rd, form, fq = date.fromisoformat(doc["report_date"]), doc["form"], doc["fiscal_quarter"]
    p = parse_filing((paths.base / doc["path"]).read_bytes(), doc.get("filer_name") or doc.get("company", ""))
    if not any(r.entity == "parent" for r in p.rows):  # nie je to spoločný výkaz (alebo iný názov) → ignorovať
        for r in p.rows:
            r.entity = "none"
    gold = gold_values(p, rd, form, fq)
    # pri "max" a "accept_any" je správnych viac konceptov – riadok je pozitívny pri ktoromkoľvek z nich
    accept = {m: (set(METRICS[m]["concepts"]) if METRICS[m].get("gold") == "max" or METRICS[m].get("accept_any")
                  else {c}) for m, (c, _, _) in gold.items()}
    meta = {"doc_id": did, **{k: doc.get(k, "") for k in DOC_META[1:]}}
    form_tok = "form_" + form.replace("-", "").lower()
    rows = []
    for r in p.rows:
        target = "OTHER"
        for m, concepts in accept.items():
            kind = METRICS[m]["kind"]
            # XBRL fakt musí byť presne v stĺpci, z ktorého by sa hodnota čítala
            idx = choose_column(r.periods, len(r.values), required_months(kind, form, fq), 3 * fq)
            f = r.facts[idx] if idx is not None and idx < len(r.facts) else None
            if f is not None and f.concept in concepts and period_matches(kind, p.contexts.get(f.context_id),
                                                                           rd, form, fq):
                target = m
                break
        rows.append({**meta, "table_idx": r.table_idx, "row_idx": r.row_idx, "label_text": r.label,
                     "context": f"{form_tok} {r.context}",
                     "row_ctx": row_tokens(r.section, r.prev_label, r.next_label, r.stmt, r.entity,
                                           r.periods, r.values[0], r.decimals[0]),
                     "scale": r.scale, "values": r.values, "decimals": r.decimals, "periods": r.periods, "entity": r.entity,
                     "stmt": r.stmt, "value0": r.values[0], "n_values": len(r.values), "target": target})
    gold_df = pd.DataFrame([{**meta, "metric": m, "concept": c, "gold_value": v,
                             "gold_alt": ";".join(f"{x:.6g}" for x in alts)} for m, (c, v, alts) in gold.items()])
    return pd.DataFrame(rows), gold_df


def build_dataset(paths: Paths, log: Callable = print, rebuild: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spracuje nové dokumenty z manifestu (staršie berie z cache) a vráti celý dataset."""
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    rows, gold = [], []
    for i, doc in enumerate(manifest, 1):
        cache = paths.doc_cache / f"{doc_id(doc)}_v{PARSER_VERSION}.pkl"
        if rebuild or not cache.exists():
            log(f"  parsujem {doc_id(doc)} ({i}/{len(manifest)})")
            pd.to_pickle(process_doc(paths, doc), cache)
        r, g = pd.read_pickle(cache)
        if r.empty:
            log(f"  ! {doc_id(doc)}: v dokumente sa nenašli žiadne tabuľky s číslami – skontroluj ho "
                f"(python main.py diagnose {doc['ticker']})")
        rows.append(r)
        gold.append(g)
    rows_df, gold_df = pd.concat(rows, ignore_index=True), pd.concat(gold, ignore_index=True)
    log(f"Dataset: {len(rows_df):,} riadkov tabuliek, {int((rows_df.target != 'OTHER').sum()):,} označených, "
        f"{rows_df.doc_id.nunique()} dokumentov, {rows_df.ticker.nunique()} firiem")
    return rows_df, gold_df
