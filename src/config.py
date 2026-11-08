"""Konfigurácia projektu: roky, sledované metriky, cesty."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# jednoduché načítanie .env (bez ďalšej knižnice)
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"'))


def user_agent() -> str:
    """SEC vyžaduje User-Agent s menom a e-mailom (Fair Access policy)."""
    return os.environ.get("SEC_USER_AGENT", "").strip()


# Dva roky → štvrťroky + medziročné (YoY) porovnanie. Fiškálne roky podľa firmy.
DEFAULT_YEARS = [2024, 2025]
CATALOG_PATH = ROOT / "catalog" / "companies.csv"

# kind:
#   duration_q   – výkaz ziskov a strát: v 10-Q je 1. stĺpec "tri mesiace"
#   duration_ytd – výkaz cash flow: v 10-Q je 1. stĺpec kumulatívne od začiatku roka
#   instant      – súvaha: stav k dátumu
# concepts: XBRL koncepty (us-gaap) v poradí priority – zdroj trénovacích labelov
#           a referenčných hodnôt. Pre iné odvetvia stačí doplniť alternatívy.
METRICS: dict[str, dict] = {
    "revenue":             {"kind": "duration_q",   "concepts": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                                                                  "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
                            "accept_any": True},  # „Total revenues and other income“ aj „Sales…“ sú prijateľné
    "net_income":          {"kind": "duration_q",   "concepts": ["NetIncomeLoss"]},
    "eps_diluted":         {"kind": "duration_q",   "concepts": ["EarningsPerShareDiluted"], "per_share": True},
    "operating_cash_flow": {"kind": "duration_ytd", "concepts": ["NetCashProvidedByUsedInOperatingActivities"]},
    "capex":               {"kind": "duration_ytd", "concepts": ["PaymentsToAcquirePropertyPlantAndEquipment",
                                                                  "PaymentsToAcquireProductiveAssets",
                                                                  "PaymentsToAcquireOilAndGasPropertyAndEquipment"], "outflow": True,
                            "gold": "max"},  # pri viacerých riadkoch capex (napr. EOG) berieme najväčší
    "dividends_paid":      {"kind": "duration_ytd", "concepts": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], "outflow": True,
                            "optional": True},
    "buybacks":            {"kind": "duration_ytd", "concepts": ["PaymentsForRepurchaseOfCommonStock"], "outflow": True,
                            "optional": True},
    # pre EBITDA = zisk pred zdanením + úroky + odpisy
    "pretax_income":       {"kind": "duration_q",   "concepts": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                                                                  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]},
    "interest_expense":    {"kind": "duration_q",   "concepts": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                                                                  "InterestAndDebtExpense"], "outflow": True, "optional": True},
    "depreciation":        {"kind": "duration_ytd", "concepts": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                                                                  "DepreciationAmortizationAndAccretionNet"], "outflow": True,
                            "gold": "max"},
    "cash":                {"kind": "instant",      "concepts": ["CashAndCashEquivalentsAtCarryingValue"], "positive": True},
    "total_equity":        {"kind": "instant",      "concepts": ["StockholdersEquity"]},
    "long_term_debt":      {"kind": "instant",      "concepts": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
                            "positive": True},
    # krátkodobý dlh = krátkodobé pôžičky + splatná časť dlhodobého dlhu (firmy ich uvádzajú rôzne)
    "short_term_borrowings": {"kind": "instant",    "concepts": ["ShortTermBorrowings", "CommercialPaper"], "optional": True,
                              "positive": True},
    "current_ltd":         {"kind": "instant",      "concepts": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                                                                  "DebtCurrent"], "optional": True, "positive": True},
}

DEFAULT_SCALE = 1e6          # ak tabuľka neuvádza jednotky, predpokladáme milióny USD
CONFIDENCE_THRESHOLD = 0.15  # pod touto pravdepodobnosťou hodnotu nevyplníme (NaN)
OPTIONAL_THRESHOLD = 0.35    # položky, ktoré firma nemusí mať (úroky, odkupy, krátkodobé pôžičky…)


@dataclass
class Paths:
    base: Path

    @property
    def raw(self) -> Path: return self.base / "data" / "raw"
    @property
    def processed(self) -> Path: return self.base / "data" / "processed"
    @property
    def doc_cache(self) -> Path: return self.processed / "docs"
    @property
    def models(self) -> Path: return self.base / "models"
    @property
    def output(self) -> Path: return self.base / "output"
    @property
    def audit(self) -> Path: return self.output / "audit"
    @property
    def manifest(self) -> Path: return self.raw / "manifest.json"
    @property
    def kpis(self) -> Path: return self.output / "investor_kpis.csv"

    def ensure(self) -> "Paths":
        for p in (self.raw, self.doc_cache, self.models, self.audit):
            p.mkdir(parents=True, exist_ok=True)
        return self
