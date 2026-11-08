"""Poctivé vyhodnotenie: leave-one-company-out (model nikdy nevidel firmu, ktorú číta)."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import classification_report

from .config import METRICS
from .model import FEATURES, extract, train


def values_match(metric: str, extracted: float, gold: float) -> bool:
    if pd.isna(extracted) or pd.isna(gold):
        return False
    if METRICS[metric].get("per_share"):
        return abs(extracted - gold) <= 0.015
    return abs(extracted - gold) <= max(0.005 * abs(gold), 1e6)


def leave_one_company_out(rows: pd.DataFrame, gold: pd.DataFrame, tickers: list[str],
                          log: Callable = print) -> tuple[pd.DataFrame, str]:
    """Pre každú vybranú firmu: model natrénovaný na VŠETKÝCH ostatných firmách v cache."""
    if rows.ticker.nunique() < 2:
        raise RuntimeError("Na tréning treba aspoň 2 spoločnosti – vyber ďalšiu firmu.")
    extracted, y_true, y_pred = [], [], []
    for t in tickers:
        train_rows, test_rows = rows[rows.ticker != t], rows[rows.ticker == t]
        if test_rows.empty:
            continue
        model = train(train_rows)
        log(f"  {t}: model natrénovaný na {train_rows.ticker.nunique()} iných firmách, číta {test_rows.doc_id.nunique()} dokumentov")
        extracted.append(extract(model, test_rows))
        y_true += list(test_rows.target)
        y_pred += list(model.predict(test_rows[FEATURES]))
    ex = pd.concat(extracted, ignore_index=True)
    ex = ex.merge(gold[["doc_id", "metric", "gold_value", "gold_alt"]], on=["doc_id", "metric"], how="left")
    ex["match"] = [any(values_match(m, e, float(a)) for a in str(alt).split(";") if a not in ("", "nan"))
                   or values_match(m, e, g) for m, e, g, alt in zip(ex.metric, ex.value, ex.gold_value, ex.gold_alt)]
    labels = [m for m in METRICS if m in set(y_true)]
    report = classification_report(y_true, y_pred, labels=labels, zero_division=0)
    return ex, report


def accuracy_table(ex: pd.DataFrame, by: str) -> pd.DataFrame:
    scored = ex[ex.gold_value.notna()]
    t = scored.groupby(by).match.agg(["mean", "sum", "count"]).rename(
        columns={"mean": "accuracy_pct", "sum": "correct", "count": "n"})
    t["accuracy_pct"] = (t["accuracy_pct"] * 100).round(1)
    if by == "metric":
        t = t.reindex([m for m in METRICS if m in t.index])
    return t


def overall_accuracy(ex: pd.DataFrame) -> float:
    scored = ex[ex.gold_value.notna()]
    return float(np.round(scored.match.mean() * 100, 1)) if len(scored) else float("nan")
