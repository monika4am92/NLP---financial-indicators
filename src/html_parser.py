"""Rozparsovanie HTML podania na riadky tabuliek (text + čísla) a XBRL fakty.

Model dostáva LEN text riadku a jeho okolie (sekcia, susedné riadky, nadpis tabuľky).
Inline XBRL značky (ix:nonFraction) slúžia iba na automatické označenie
trénovacích dát a na overenie presnosti – pri nových dokumentoch (PDF,
zahraničné firmy) netreba.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import warnings

from bs4 import BeautifulSoup, Tag
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from .config import DEFAULT_SCALE

PARSER_VERSION = 6  # zmena parsera → cache spracovaných dokumentov sa vytvorí nanovo


def _local(t) -> str:
    return t.name.split(":")[-1].lower() if isinstance(t, Tag) and t.name else ""


def _is_fact(t) -> bool:
    return _local(t) == "nonfraction"


@dataclass
class Context:
    start: date | None
    end: date | None
    instant: date | None
    has_dims: bool  # kontext so segmentom/dimenziou = nie konsolidovaný súčet materskej firmy


@dataclass
class Fact:
    concept: str
    value: float     # absolútna hodnota v USD (resp. USD/akcia)
    context_id: str


@dataclass
class Row:
    table_idx: int
    row_idx: int
    label: str
    context: str            # text nad tabuľkou + hlavička
    scale: float
    values: list[float]
    decimals: list[int]     # počet desatinných miest v texte (EPS má vždy 2, počet akcií nie)
    facts: list            # XBRL fakt ku každej hodnote (None = bunka bez značky); len na tvorbu labelov
    section: str = ""       # posledný nadpisový riadok nad týmto riadkom ("Earnings per share:")
    prev_label: str = ""
    next_label: str = ""
    stmt: str = "other"     # is / bs / cf / eq / other
    entity: str = "none"    # parent / other / none (spoločné výkazy materskej a dcérskych firiem)
    periods: list[int] = field(default_factory=list)  # obdobia stĺpcových blokov v mesiacoch, 0 = od zač. roka


@dataclass
class ParsedFiling:
    rows: list[Row]
    facts: list[Fact]
    contexts: dict[str, Context]


# ---------- čísla a jednotky ----------
_NUM = re.compile(r"^\(?-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?\)?$")
_DASHES = {"—", "–", "-", "−", "-0-"}


def parse_values_ext(cells: list[str]) -> tuple[list[float], list[bool]]:
    """Čísla v poradí stĺpcov + príznak desatinného miesta. (1,234) → -1234, '—' → 0."""
    s = " ¦ ".join(cells).replace("$", "")
    s = re.sub(r"\(\s*¦\s*", "(", s)
    s = re.sub(r"\s*¦\s*\)", ")", s)
    vals, decs = [], []
    for p in s.split("¦"):
        p = p.strip().replace(" ", "").replace("\xa0", "")
        if not p or "%" in p:
            continue
        if p in _DASHES:
            vals.append(0.0)
            decs.append(0)
        elif _NUM.match(p):
            neg = p.startswith("(") or p.startswith("-")
            v = float(p.strip("()").lstrip("-").replace(",", ""))
            vals.append(-v if neg else v)
            decs.append(len(p.strip("()").split(".")[1]) if "." in p else 0)
    return vals, decs


def parse_values(cells: list[str]) -> list[float]:
    return parse_values_ext(cells)[0]


def parse_cells_aligned(tds: list) -> tuple[list[float], list[bool], list]:
    """Ako parse_values_ext, ale ku každej hodnote vráti aj XBRL fakt z tej istej bunky (alebo None).
    Vďaka tomu label riadku zodpovedá presne stĺpcu, z ktorého sa hodnota číta."""
    tokens: list[list] = []  # [text, fact]
    for td in tds:
        text = _clean(td.get_text(" ")).replace("$", "").strip()
        if not text:
            continue
        f = td.find(_is_fact)
        if text == ")" and tokens:
            tokens[-1][0] += ")"
            continue
        if text == "(":
            tokens.append(["(", f])
            continue
        if tokens and tokens[-1][0] == "(":
            tokens[-1][0] += text
            tokens[-1][1] = tokens[-1][1] or f
            continue
        tokens.append([text, f])
    vals, decs, facts = [], [], []
    for text, f in tokens:
        v, d = parse_values_ext([text])
        if len(v) == 1:
            vals.append(v[0])
            decs.append(d[0])
            facts.append(_parse_fact(f) if f is not None else None)
    return vals, decs, facts


def detect_scale(*texts: str) -> float:
    for text in texts:  # prednosť má hlavička tabuľky, potom text pred ňou
        t = text.lower()
        if re.search(r"in billions|billions of", t):
            return 1e9
        if re.search(r"in millions|millions of|\(millions|\$\s?millions|\bmillions\b", t):
            return 1e6
        if re.search(r"in thousands|thousands of|\(thousands|\bthousands\b", t):
            return 1e3
    return DEFAULT_SCALE


# ---------- obdobia stĺpcov ----------
_WORD_MONTHS = {"three": 3, "3": 3, "six": 6, "6": 6, "nine": 9, "9": 9, "twelve": 12, "12": 12}
_PERIOD_RE = re.compile(
    r"\b(three|six|nine|twelve|3|6|9|12)[\s-]+months?\b"
    r"|\b(\d{1,2})[\s-]+weeks?\b"
    r"|\bquarters?\s+ended\b|\b(?:first|second|third|fourth)\s+quarters?\b"
    r"|\byears?\s+ended\b|\bfiscal\s+years?\b"
    r"|\byear[\s-]+to[\s-]+date\b|\bytd\b", re.I)


def detect_periods(text: str) -> list[int]:
    """Poradie období v hlavičke: [3, 9] = 'Three Months … Nine Months …'. 0 = od začiatku roka."""
    out: list[int] = []
    for m in _PERIOD_RE.finditer(text):
        g = m.group(0).lower()
        if m.group(1):
            months = _WORD_MONTHS[m.group(1).lower()]
        elif m.group(2):
            months = round(int(m.group(2)) / 4.33)
        elif "year" in g and ("to" in g or "date" in g) or g == "ytd":
            months = 0
        elif "year" in g:
            months = 12
        else:
            months = 3
        if not out or out[-1] != months:
            out.append(months)
    return out


def required_months(kind: str, form: str, fq: int) -> int | None:
    """Koľko mesiacov má mať stĺpec pre danú metriku (None = súvaha, stav k dátumu)."""
    if kind == "instant":
        return None
    if form == "10-K" or fq == 4:
        return 12
    return 3 if kind == "duration_q" else 3 * int(fq)


def choose_column(periods: list[int], n_values: int, required: int | None, ytd_months: int) -> int | None:
    """Index stĺpca pre požadované obdobie. None = tabuľka dané obdobie neobsahuje."""
    if required is None or not periods:
        return 0
    k = len(periods)
    width = n_values // k if n_values % k == 0 and n_values >= k else None
    for i, m in enumerate(periods):
        months = ytd_months if m == 0 else m
        if abs(months - required) <= 1:
            if i == 0:
                return 0
            return i * width if width else None
    return None


# ---------- typ výkazu a entita ----------
_STMT_PATTERNS = [
    ("cf", r"cash\s+flows?"),
    ("bs", r"balance\s+sheets?|financial\s+(?:position|condition)"),
    ("eq", r"(?:stockholders|shareholders|shareowners)['’]?\s+equity|changes\s+in\s+equity"),
    ("is", r"statements?\s+of\s+(?:consolidated\s+)?(?:income|operations|earnings|comprehensive)|income\s+statements?"),
]
_TITLE_RE = re.compile(r"(?:condensed\s+)?(?:consolidated\s+)?(?:statements?\s+of|balance\s+sheets?|income\s+statements?)")
_SUFFIX = r"(?:corporation|corp|incorporated|inc|company|co|llc|lp|l\.p|plc|ltd|limited|holdings|n\s?v|sa|ag)"
_STOP = {"corporation", "corp", "incorporated", "inc", "company", "co", "llc", "lp", "plc", "ltd", "the",
         "holdings", "holding", "group", "de", "new", "limited", "nv", "sa", "ag"}


def statement_type(text: str) -> str:
    best, pos = "other", -1
    for name, pat in _STMT_PATTERNS:
        for m in re.finditer(pat, text):
            if m.start() > pos:
                best, pos = name, m.start()
    return best


def parent_core(company: str) -> str:
    """'Duke Energy CORP' → 'duke energy' (meno bez právnej formy)."""
    name = re.sub(r"\(.*?\)|/[a-z]{2}/", " ", company.lower())
    toks = re.sub(r"[^a-z0-9& ]", " ", name).split()
    while toks and toks[-1] in _STOP:
        toks.pop()
    while toks and toks[0] == "the":
        toks.pop(0)
    return " ".join(toks)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9& ]", " ", text)).strip()


def entity_of(text: str, core: str) -> str:
    """Komu patrí výkaz: názov entity pri nadpise 'Consolidated Statements of …'.
    Väčšinou je tesne pred nadpisom, v niektorých 10-K (napr. Southern) až za ním."""
    if not core:
        return "none"
    matches = list(_TITLE_RE.finditer(text))
    if not matches:
        return "none"
    m = matches[-1]
    before = _norm(text[max(0, m.start() - 90):m.start()])
    after = _norm(text[m.end():m.end() + 160])
    core_re = re.escape(core).replace(r"\ ", r"\s+")
    sub = r"(?:\s+and\s+subsidiar\w*(?:\s+compan\w*)?)?"
    if re.search(rf"{core_re}(?:\s+{_SUFFIX})*{sub}(?:\s+unaudited)?$", before):
        return "parent"
    if re.search(rf"(?:\b{_SUFFIX}|\band\s+subsidiar\w*(?:\s+compan\w*)?)(?:\s+unaudited)?$", before):
        return "other"
    # názov za nadpisom (napr. Southern 10-K): len hneď za nadpisom, voliteľne po „for the years ended … 2023“,
    # aby sa nezachytila náhodná zmienka o dcérskej firme v texte poznámky
    lead = (r"^(?:(?:income|operations|earnings|comprehensive|loss|cash|flows?|financial|position|condition|"
            r"capitalization|changes|in|stockholders|shareholders|common|equity|and)\s+)*"
            r"(?:(?:for\s+the\s+(?:years?|periods?|three|six|nine|twelve|quarters?)\b(?:\s+[a-z]+){0,4}|at|as\s+of)"
            r"(?:\s+[a-z]+)?(?:\s+\d{1,4}){1,4}(?:\s+and\s+\d{4})?\s+)?")
    stop = r"(?=\s+(?:\d|annual|report|unaudited|in\s+millions)|$)"
    if re.search(rf"{lead}{core_re}(?:\s+{_SUFFIX})*{sub}{stop}", after):
        return "parent"
    if re.search(rf"{lead}(?:[a-z&]+\s+){{0,5}}?(?:{_SUFFIX}|and\s+subsidiar\w*(?:\s+compan\w*)?){stop}", after):
        return "other"
    return "none"


# ---------- XBRL ----------
def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def clean_label(text: str) -> str:
    text = re.sub(r"\((\w|\d{1,2})\)$", "", _clean(text))  # poznámka pod čiarou (a), (1)
    return text.strip(" :")


def _parse_fact(t: Tag) -> Fact:
    txt = t.get_text(strip=True)
    num = re.sub(r"[^\d.]", "", txt)
    val = float(num) if num and num != "." else 0.0
    try:
        val *= 10 ** int(t.get("scale", "0") or 0)
    except ValueError:
        pass
    if t.get("sign") == "-":
        val = -val
    return Fact(t.get("name", "").split(":")[-1], val, t.get("contextref", ""))


def _parse_contexts(soup: BeautifulSoup) -> dict[str, Context]:
    out = {}
    for c in soup.find_all(lambda t: _local(t) == "context"):
        def d(name: str):
            el = c.find(lambda t: _local(t) == name)
            return date.fromisoformat(el.get_text(strip=True)[:10]) if el else None
        has_dims = c.find(lambda t: _local(t) in ("segment", "scenario")) is not None
        out[c.get("id")] = Context(d("startdate"), d("enddate"), d("instant"), has_dims)
    return out


def _preceding_text(table: Tag, n_chars: int = 300) -> str:
    parts, total = [], 0
    for s in table.find_all_previous(string=True, limit=120):
        t = _clean(str(s))
        if t:
            parts.append(t)
            total += len(t)
            if total > n_chars:
                break
    return " ".join(reversed(parts))[-n_chars:]


def parse_filing(html: str | bytes, company: str = "") -> ParsedFiling:
    soup = BeautifulSoup(html, "lxml")
    contexts = _parse_contexts(soup)
    facts = [_parse_fact(t) for t in soup.find_all(_is_fact)]
    for h in soup.find_all(lambda t: _local(t) == "header"):  # skrytá XBRL hlavička
        h.decompose()
    core = parent_core(company)

    rows: list[Row] = []
    for ti, table in enumerate(soup.find_all("table")):
        trs = table.find_all("tr")
        if len(trs) < 2:
            continue
        parsed = []  # (ri, label, values, decimals, aligned facts, text)
        for ri, tr in enumerate(trs):
            tds = tr.find_all(["td", "th"])
            cells = [_clean(td.get_text(" ")) for td in tds]
            li = next((i for i, c in enumerate(cells) if re.search(r"[A-Za-z]{2,}", c)), None)
            label = clean_label(cells[li]) if li is not None else ""
            vals, decs, vfacts = parse_cells_aligned(tds[li + 1:]) if li is not None else ([], [], [])
            parsed.append((ri, label, vals, decs, vfacts, " ".join(c for c in cells if c)))
        first_data = next((i for i, p in enumerate(parsed) if p[1] and p[2]), None)
        if first_data is None:
            continue
        head = " ".join(p[5] for p in parsed[:max(first_data, 1)][:6])
        before = _preceding_text(table)
        scale = detect_scale(head, before)
        context = (before + " | " + head).lower()[-450:]
        periods = detect_periods(head) or detect_periods(before[-200:])
        stmt = statement_type(context)
        entity = entity_of(context, core)

        labels = [p[1] for p in parsed if p[1]]
        section, li_idx = "", -1
        for ri, label, vals, decs, vfacts, _ in parsed:
            if not label:
                continue
            li_idx += 1
            if not vals:
                section = label  # nadpisový riadok bez čísel
                continue
            rows.append(Row(ti, ri, label, context, scale, vals, decs, vfacts, section,
                            labels[li_idx - 1] if li_idx > 0 else "",
                            labels[li_idx + 1] if li_idx + 1 < len(labels) else "",
                            stmt, entity, periods))
    return ParsedFiling(rows, facts, contexts)
