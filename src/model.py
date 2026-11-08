"""NLP model: klasifikácia riadkov tabuliek do finančných metrík + výber hodnoty."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from .config import CONFIDENCE_THRESHOLD, METRICS, OPTIONAL_THRESHOLD
from .html_parser import choose_column, required_months

META_COLS = ["doc_id", "ticker", "company", "sector", "form", "fiscal_year", "fiscal_quarter", "report_date"]
FEATURES = ["label_text", "context", "row_ctx"]


def row_tokens(section: str, prev_label: str, next_label: str, stmt: str, entity: str,
               periods: list[int], value: float, has_decimals: bool) -> str:
    """Okolie riadku ako text: nadpis sekcie, susedné riadky a štrukturálne značky.
    Napr. 'Diluted' pod 'Earnings per share' vs. 'Diluted' pod 'Weighted average shares'."""
    v = abs(value)
    mag = "mag_zero" if v == 0 else f"mag{min(int(np.log10(v)) if v >= 1 else 0, 4)}"
    sign = "val_neg" if value < 0 else "val_zero" if value == 0 else "val_pos"
    per = [f"per_first_{'ytd' if periods[0] == 0 else periods[0]}m"] if periods else ["per_none"]
    per += [f"per_has_{'ytd' if p == 0 else p}m" for p in periods]
    tokens = [f"stmt_{stmt}", f"ent_{entity}", sign, mag, "val_dec" if has_decimals else "val_int", *per]
    return f"sekcia {section} | pred {prev_label} | po {next_label} | {' '.join(tokens)}".lower()


def build_model() -> Pipeline:
    features = ColumnTransformer([
        # slová a dvojice slov z popisu riadku ("net income attributable")
        ("label_words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True), "label_text"),
        # znakové n-gramy – robustné voči variantom ("earnings"/"earning", "Long-Term"/"long term")
        ("label_chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True,
                                        max_features=60000), "label_text"),
        # kontext tabuľky – nadpis výkazu, jednotky, obdobia
        ("context", TfidfVectorizer(ngram_range=(1, 2), max_features=8000, sublinear_tf=True), "context"),
        # okolie riadku – sekcia, susedia, typ výkazu, entita, znamienko a veľkosť čísla
        ("row_ctx", TfidfVectorizer(ngram_range=(1, 2), max_features=12000, sublinear_tf=True), "row_ctx"),
    ], transformer_weights={"label_words": 1.0, "label_chars": 1.0, "context": 0.5, "row_ctx": 0.8})
    clf = LogisticRegression(max_iter=3000, C=5.0, class_weight="balanced")
    return Pipeline([("features", features), ("clf", clf)])


def _training_sample(rows: pd.DataFrame, other_share: float = 0.2, seed: int = 42) -> pd.DataFrame:
    """Všetky riadky z tabuliek s aspoň jedným označeným riadkom (ťažké negatívne príklady)
    + náhodných 20 % ostatných. Tréning je tak niekoľkonásobne rýchlejší bez straty presnosti."""
    key = rows["doc_id"] + "#" + rows["table_idx"].astype(str)
    pos_tables = set(key[rows["target"] != "OTHER"])
    in_pos = key.isin(pos_tables)
    rest = rows[~in_pos].sample(frac=other_share, random_state=seed)
    return pd.concat([rows[in_pos], rest])


def train(rows: pd.DataFrame) -> Pipeline:
    sample = _training_sample(rows)
    model = build_model()
    model.fit(sample[FEATURES], sample["target"])
    return model


# jazykové pravidlá pre popisy riadkov, ktoré model z malého počtu firiem nemusí zachytiť
# „Long-term debt, less current portion“ = dlhodobý dlh; „Less: current portion“ (na začiatku) = krátkodobá časť
_NONCURRENT = re.compile(r"(?<=\S)[,\s]+(?:less|net\s+of|excluding|excl\.?)\b[^,]*\bcurrent\b|non-?current", re.I)
_OUTFLOW_BAD = re.compile(r"\b(?:sales?|proceeds|disposals?|dispositions?|issuances?|reimburse\w*)\b", re.I)
_CURRENT = re.compile(r"due\s+within\s+one\s+year|current\s+(?:portion|maturit)|short-term", re.I)
_PARENT_NI = re.compile(r"attributable\s+to(?!\s+(?:non-?controlling|minority|redeemable))", re.I)
_AVAILABLE_NI = re.compile(r"available\s+(?:to|for)", re.I)


def _label_ok(metric: str, label: str) -> bool:
    if metric in ("capex", "buybacks", "dividends_paid"):  # výdavok, nie príjem z predaja/emisie
        return not _OUTFLOW_BAD.search(label)
    if metric == "current_ltd":
        return not _NONCURRENT.search(label)
    if metric == "long_term_debt":
        return not (_CURRENT.search(label) and not _NONCURRENT.search(label))
    return True


# v ktorom výkaze má metrika svoj „domov“ – pri podobne pravdepodobných riadkoch má prednosť
HOME_STATEMENT = {"revenue": "is", "net_income": "is", "eps_diluted": "is", "pretax_income": "is",
                  "interest_expense": "is", "operating_cash_flow": "cf", "capex": "cf", "dividends_paid": "cf",
                  "buybacks": "cf", "depreciation": "cf", "cash": "bs", "total_equity": "bs",
                  "long_term_debt": "bs", "short_term_borrowings": "bs", "current_ltd": "bs"}


def _pick_value(row: pd.Series, spec: dict) -> tuple[float, int] | None:
    """(hodnota, kvalita obdobia): 2 = hlavička potvrdzuje obdobie v 1. stĺpci, 1 = iný stĺpec, 0 = nevedno."""
    vals = row["values"] if isinstance(row.get("values"), (list, tuple)) else [row["value0"]]
    periods = list(row.get("periods")) if isinstance(row.get("periods"), (list, tuple)) else []
    fq = int(row["fiscal_quarter"] or 4)
    req = required_months(spec["kind"], row["form"], fq)
    idx = choose_column(periods, len(vals), req, 3 * fq)
    if idx is None or idx >= len(vals):
        return None
    # v 10-Q rozhoduje, či hlavička potvrdzuje obdobie (3 mesiace vs. od začiatku roka);
    # v 10-K je prvý stĺpec vždy celý rok a hlavné výkazy majú v hlavičke len roky → bez rozdielu
    if req is None or req == 12:
        quality = 1
    else:
        quality = 0 if not periods else (2 if idx == 0 else 1)
    v = vals[idx]
    if spec.get("per_share"):
        decs = row.get("decimals") if isinstance(row.get("decimals"), (list, tuple)) else None
        if abs(v) >= 1000 or (decs is not None and idx < len(decs) and decs[idx] < 2 and v != 0):
            return None   # EPS je vždy na 2 desatinné miesta; počet akcií nie
        return v, quality
    return v * row["scale"], quality


def extract(model: Pipeline, rows: pd.DataFrame, threshold: float = CONFIDENCE_THRESHOLD) -> pd.DataFrame:
    """Pre každý dokument a metriku vyberie spomedzi najpravdepodobnejších riadkov ten, ktorý
    (1) obsahuje požadované obdobie (3 mesiace / od začiatku roka / rok),
    (2) v spoločných výkazoch patrí materskej firme, nie dcérskej,
    (3) je v „domovskom“ výkaze metriky (tržby vo výsledovke, capex v cash flow, dlh v súvahe)."""
    rows = rows.reset_index(drop=True)
    if "row_ctx" not in rows:
        rows["row_ctx"] = ""
    proba = model.predict_proba(rows[FEATURES])
    classes = list(model.classes_)
    out = []
    for _, idx in rows.groupby("doc_id").indices.items():
        sub = rows.iloc[idx]
        entities = sub["entity"] if "entity" in sub else pd.Series("none", index=sub.index)
        stmts = sub["stmt"] if "stmt" in sub else pd.Series("other", index=sub.index)
        combined = bool((entities == "parent").any())  # spoločný výkaz materskej a dcérskych firiem
        for metric, spec in METRICS.items():
            if metric not in classes:
                continue
            col = proba[idx, classes.index(metric)]
            order = np.argsort(-col)[:25]
            cands = []
            for k in order:
                if combined and entities.iloc[k] == "other":  # výkazy dcérskych firiem vynechať
                    continue
                if not _label_ok(metric, sub.iloc[k]["label_text"]):
                    continue
                picked = _pick_value(sub.iloc[k], spec)
                if picked is not None:
                    cands.append((k, float(col[k]), picked[0], picked[1]))
            if not cands:
                continue
            best_p = max(c[1] for c in cands)
            strong = [c for c in cands if c[1] >= 0.5 * best_p]
            if metric == "net_income":  # zisk pripadajúci akcionárom má prednosť pred ziskom vrátane menšinových podielov
                attr = [c for c in strong if _PARENT_NI.search(sub.iloc[c[0]]["label_text"])]
                avail = [c for c in strong if _AVAILABLE_NI.search(sub.iloc[c[0]]["label_text"])]
                strong = attr or avail or strong
            home = HOME_STATEMENT.get(metric)

            def support(c):  # koľko silných kandidátov má rovnakú hodnotu (výkaz, MD&A, poznámky sa zhodujú)
                return sum(abs(o[2] - c[2]) <= max(0.005 * abs(c[2]), 1e-9) for o in strong)

            # poradie: domovský výkaz → materská firma (spoločné výkazy) → potvrdené obdobie → istota → zhoda hodnôt
            k, conf, val, _ = max(strong, key=lambda c: (stmts.iloc[c[0]] == home, entities.iloc[c[0]] == "parent",
                                                         c[3], round(c[1], 2), support(c), c[1]))
            r = sub.iloc[k]
            if spec.get("outflow") or spec.get("positive"):
                val = abs(val)
            limit = OPTIONAL_THRESHOLD if spec.get("optional") else threshold
            out.append({**{c: r.get(c, "") for c in META_COLS}, "metric": metric,
                        "value": val if conf >= limit else np.nan,
                        "confidence": round(conf, 3), "source_row": r.label_text})
    return pd.DataFrame(out)
