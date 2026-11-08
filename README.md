# NLP extrakcia finančných ukazovateľov z výkazov SEC

Projekt stiahne štvrťročné (10-Q) a ročné (10-K) výkazy amerických spoločností zo SEC EDGAR,
**natrénuje NLP model**, ktorý v textoch výkazov nájde vybrané finančné údaje, overí jeho presnosť
a výsledok uloží do jedného prehľadného súboru **`output/investor_kpis.csv`** so štvrťročnými
a ročnými ukazovateľmi pre investorov – od výsledkov hospodárenia až po **ocenenie akcie**
(P/E, EV/EBITDA, FCF a dividendový výnos). Výsledky zobrazuje **Streamlit aplikácia**.

- Odvetvia a firmy sa vyberajú z katalógu `catalog/companies.csv` (rozbaľovací zoznam v aplikácii).
  Pripravené sú: Energetika, Čistá energia, Technológie, Zdravotníctvo, Spotrebný tovar.
- Predvolene sa spracúvajú fiškálne roky **2024 a 2025** → štvrťroky + medziročné (r/r) zmeny.
- Fiškálne roky sa riadia firmou (Apple končí v septembri, NVIDIA v januári…).

---

## 1. Inštalácia vo Visual Studio Code (Windows)

1. Nainštaluj **Python 3.11+** (python.org, zaškrtni *Add to PATH*) a vo VS Code rozšírenie **Python** (Microsoft).
2. Rozbaľ projekt a otvor priečinok: *File → Open Folder… → `energy_nlp`*.
3. V termináli (*Terminal → New Terminal*, PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # ak to zablokuje politika: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env               # v .env doplň svoje meno a e-mail
```

4. `Ctrl+Shift+P` → *Python: Select Interpreter* → `.venv`.

> **Prečo e-mail?** SEC vyžaduje, aby každý automatický klient poslal v hlavičke `User-Agent`
> meno a kontakt, a povoľuje max. 10 požiadaviek za sekundu. Bez toho vráti chybu 403. Kód to dodržiava.

## 2. Spustenie

### Najjednoduchšie: aplikácia
```powershell
streamlit run app.py
```
Otvorí sa prehliadač. Na karte *Spracovať firmy* vyber odvetvie (alebo „Všetky odvetvia“), firmy a roky
a klikni „Stiahnuť a spracovať“. Spracovanie beží **na pozadí ako samostatný proces** – priebeh sa
zobrazuje priamo v aplikácii a kliknutie ani zatvorenie prehliadača ho neprerušia.

### Z príkazového riadku
```powershell
python main.py sectors                                   # katalóg odvetví a firiem
python main.py run --sector Energetika                   # celé odvetvie, roky 2024–2025
python main.py run --tickers XOM CVX COP --years 2024 2025
python main.py run --all                                 # všetky firmy z katalógu naraz
python main.py diagnose XOM                              # čo sa pre firmu stiahlo/spracovalo
python main.py add NUE --sector "Materiály" --name "Nucor"   # nová firma do katalógu
python main.py prices                                    # aktualizovať ceny akcií a ocenenie
python main.py kpi                                       # prepočítať ukazovatele bez nového tréningu
```
Vo VS Code sú tieto príkazy pripravené aj v paneli *Run and Debug* (`Ctrl+Shift+D`).

Výsledky sa **dopĺňajú**: keď spracuješ Energetiku a potom Technológie, v `investor_kpis.csv` sú obe.
Stiahnuté výkazy sa ukladajú do `data/raw/`, takže sa nesťahujú znova.

## 3. Výstup: `output/investor_kpis.csv`

Jeden riadok = jedna firma × jedno obdobie (Q1–Q4 a FY za celý rok). Kódovanie UTF-8 s BOM,
takže diakritika funguje aj pri otvorení v Exceli. Rovnaký súbor číta Streamlit aj napr. Power BI.

| Stĺpec | Názov | Prečo je dôležitý pre investora |
|---|---|---|
| `sector`, `ticker`, `company` | identifikácia | |
| `fiscal_year`, `period`, `period_end` | obdobie (Q1–Q4, FY) a dátum konca | |
| `revenue_musd` | Tržby (mil. USD) | veľkosť biznisu |
| `revenue_yoy_pct` | Rast tržieb r/r (%) | rastie firma? |
| `net_income_musd` | Čistý zisk (mil. USD) | zisk pripadajúci akcionárom |
| `net_margin_pct` | Čistá marža (%) | koľko z tržieb ostane ako zisk |
| `eps_diluted` | EPS – zisk na akciu (USD) | základ pre P/E |
| `eps_yoy_pct` | Rast EPS r/r (%) | rast zisku pre akcionára |
| `roe_pct` | ROE (%) | výnosnosť vlastného kapitálu (štvrťroky anualizované ×4) |
| `operating_cash_flow_musd` | Prevádzkový cash flow | hotovosť z prevádzky |
| `capex_musd` | CAPEX | investície do majetku – v energetike zásadné |
| `free_cash_flow_musd` | Voľný cash flow (FCF) | hotovosť k dispozícii pre akcionárov a splácanie dlhu |
| `shareholder_returns_musd` | Výplaty akcionárom | dividendy + spätné odkupy |
| `fcf_payout_pct` | Výplaty / FCF (%) | nad 100 % = výplaty z dlhu/rezerv, nie udržateľné dlhodobo |
| `net_debt_musd` | Čistý dlh | dlhodobý dlh + krátkodobé pôžičky + splatná časť dlhodobého dlhu − hotovosť (bez lízingov) |
| `net_debt_to_equity` | Čistý dlh / VK | zadlženosť: < 0,3 nízka, > 1 vysoká |
| `net_debt_to_ebitda` | Čistý dlh / EBITDA | za koľko rokov by firma splatila dlh; nad 3 = vysoké |
| `ebitda_musd` | EBITDA | prevádzkový zisk pred odpismi – základ pre EV/EBITDA |
| **Ocenenie** | *cena akcie k poslednému obchodnému dňu obdobia, výsledky za posledné 4 štvrťroky (TTM)* | |
| `price_usd`, `market_cap_musd` | Cena akcie, trhová kapitalizácia | koľko trh za firmu platí |
| `pe_ttm` | P/E | koľko rokov zisku stojí akcia; nižšie = lacnejšie |
| `ev_ebitda_ttm` | EV/EBITDA | ako P/E, ale zohľadňuje dlh – v energetike štandard |
| `pb` | P/B | cena oproti účtovnej hodnote majetku |
| `fcf_yield_pct` | FCF výnos | koľko voľnej hotovosti pripadá na investovaný dolár |
| `dividend_yield_pct` | Dividendový výnos | vyplatené dividendy / kapitalizácia |
| `shareholder_yield_pct` | Výnos pre akcionárov | (dividendy + odkupy) / kapitalizácia |
| `data_check` | kontrola kvality | `OK`, alebo ktoré hodnoty sa líšia od oficiálnych XBRL dát / chýbajú |

Pomocné a kontrolné súbory sú oddelene v `output/audit/` (detail extrakcie s istotou modelu,
referenčné hodnoty z XBRL, presnosť modelu, história behov).

### Ako vznikajú štvrťroky
- **Výsledovka:** 10-Q uvádza priamo „Three Months Ended“ → Q1–Q3. **Q4 = rok − (Q1+Q2+Q3).** Pri EPS je to aproximácia.
- **Cash flow:** 10-Q uvádza kumulatívne od začiatku roka → Q2 = H1 − Q1, Q3 = 9M − H1, Q4 = rok − 9M.
- **Súvaha:** stav ku koncu štvrťroka.

### Ocenenie a ceny akcií
- **Zdroj cien:** Yahoo Finance cez knižnicu `yfinance` (bezplatné, bez API kľúča). Je to neoficiálne
  rozhranie – ak prestane fungovať, ceny sa dajú doplniť ručne do `catalog/manual_prices.csv`
  (formát `ticker,date,close`, vzor je v `manual_prices.example.csv`); ručné ceny majú prednosť.
- **Počet akcií** sa odvodí z výkazov ako čistý zisk / zriedené EPS (vážený priemer za obdobie). Ak v období
  EPS chýba, prevezme sa počet akcií z najbližšieho obdobia tej istej firmy. P/E sa vtedy neuvádza
  (vyžaduje EPS za 4 štvrťroky), ostatné ukazovatele ocenenia áno.
- **EBITDA** = zisk pred zdanením + úrokové náklady + odpisy (ak firma úroky v tabuľke neuvádza, rátajú sa ako 0).
- **TTM** (posledné 4 štvrťroky) sa počíta len pri 4 štvrťrokoch za sebou – preto sa ocenenie
  objaví od Q4 prvého spracovaného roka.
- `output/valuation_current.csv` obsahuje **aktuálne ocenenie** (najnovšia cena + posledné 4 štvrťroky);
  aktualizuje sa príkazom `python main.py prices` alebo tlačidlom v aplikácii.
- Ocenenie dáva zmysel najmä **v porovnaní s ostatnými firmami odvetvia a s históriou firmy** –
  aplikácia preto ukazuje aj medián odvetvia.

Ide o informatívne údaje, nie investičné odporúčanie. Odvetvové údaje (pri ropných firmách objem ťažby
a realizované ceny ropy) sú v textovej časti MD&A – to je ďalší vhodný krok pre NLP.

## 4. Streamlit aplikácia (`app.py`)

| Karta | Obsah |
|---|---|
| **Prehľad** | 8 kľúčových ukazovateľov firmy so zmenou r/r, aktuálne ocenenie s mediánom odvetvia, tabuľka všetkých období |
| **Ocenenie** | P/E, EV/EBITDA, P/B a výnosy firiem odvetvia vedľa seba + medián odvetvia, graf |
| **Porovnanie** | firmy odvetvia vedľa seba pre zvolený ukazovateľ a obdobie |
| **Vývoj** | vývoj ukazovateľa v čase (štvrťroky alebo roky), max. 8 firiem |
| **Tabuľka** | filtrované dáta so slovenskými názvami stĺpcov + stiahnutie CSV |
| **Kvalita dát** | presnosť modelu, obdobia na kontrolu, z ktorého riadku výkazu model čítal |
| **Spracovať firmy** | výber odvetvia a firiem z rozbaľovacieho zoznamu, rokov, spustenie; aktualizácia cien; pridanie novej firmy do katalógu |

Bočný panel: odvetvie, firmy, štvrťroky/roky, rozsah rokov.

## 5. Ako funguje NLP model

### Problém
Výkazy sú dlhé HTML dokumenty so stovkami tabuliek a rovnaký údaj sa v každej firme volá inak
(„Total revenues and other income“, „Net sales“, „Total operating revenues“…). Čistý zisk sa navyše
objavuje aj v cash flow, v segmentoch či v MD&A – model musí vybrať správny riadok aj správne obdobie.

### Trénovacie dáta bez ručného označovania (weak supervision)
SEC vyžaduje **inline XBRL**: každé číslo vo výkaze má v HTML skrytú značku, napr.
`<ix:nonFraction name="us-gaap:NetIncomeLoss" …>`. Projekt ju využíva **len ako učiteľa**:

1. `src/html_parser.py` rozloží každú tabuľku na riadky: *popis riadku*, *kontext* (text nad tabuľkou + hlavička), *čísla v stĺpcoch*, *jednotky*.
2. `src/dataset.py` priradí riadku label (napr. `net_income`), iba ak XBRL značka **presne v stĺpci, z ktorého
   sa hodnota číta,** má správny koncept, **správne obdobie** a **nie je segmentová**. Ostatné riadky = `OTHER`.
   (Napr. v tabuľke zmien vlastného kapitálu je správny údaj až v stĺpci „Total“ – taký riadok sa preto neoznačí.)
3. Model **vidí iba text** – preto ho možno použiť aj na dokumenty bez XBRL (PDF, zahraničné firmy).

Keďže labely vznikajú automaticky, **pridanie odvetvia nič nestojí** – stačí vybrať firmy a model sa
naučí aj ich terminológiu. Model sa vždy učí zo všetkých doteraz stiahnutých výkazov.

### Model (`src/model.py`)
- **Príznaky (TF-IDF):**
  - popis riadku – slová, dvojice slov a znakové n-gramy 3–5,
  - kontext tabuľky – text nad tabuľkou a hlavička (nadpis výkazu, jednotky, obdobia),
  - **okolie riadku** – nadpis sekcie, predchádzajúci a nasledujúci riadok a štrukturálne značky:
    typ výkazu (výsledovka / súvaha / cash flow), entita (materská / dcérska firma), obdobia stĺpcov,
    znamienko a rád čísla, desatinné miesta. Vďaka tomu model rozlíši napr. „Diluted“ pod
    „Earnings per share“ (EPS) od „Diluted“ pod „Weighted-average shares“ (počet akcií).
- **Klasifikátor:** multinomiálna logistická regresia (14 metrík + OTHER). Trénuje sa na všetkých
  riadkoch tabuliek s aspoň jedným označeným riadkom + 20 % ostatných (rýchlejší tréning).
- **Výber hodnoty** – pre každý dokument a metriku najpravdepodobnejší riadok, ktorý:
  1. má v tabuľke **požadované obdobie** – stĺpec sa vyberá podľa hlavičky („Three Months“ vs.
     „Nine Months“), takže pri cash flow s 3-mesačnými aj kumulatívnymi stĺpcami sa berie správny,
  2. v **spoločných výkazoch** (utility podávajú jeden 10-K za materskú aj dcérske firmy) patrí materskej firme,
  3. je v **„domovskom“ výkaze** metriky (tržby a zisk vo výsledovke, capex v cash flow, dlh v súvahe) –
     má prednosť pred rovnako nazvaným riadkom v poznámkach, segmentoch či tabuľke zmien vlastného kapitálu,
  4. pri EPS má hodnotu na 2 desatinné miesta (počet akcií ich nemá),
  5. pri čistom zisku je to zisk **pripadajúci akcionárom** („attributable to …“), nie vrátane menšinových podielov,
  6. pri dlhu rešpektuje význam popisu („…, less current portion“ = dlhodobý dlh, „due within one year“ = krátkodobý).
- Pri nízkej istote (pod 0,15; pri položkách, ktoré firma nemusí mať, pod 0,5) hodnotu nechá prázdnu namiesto hádania.

### Vyhodnotenie
**Leave-one-company-out:** každú spracúvanú firmu číta model natrénovaný iba na ostatných firmách.
Do výstupu idú práve tieto „nevidené“ predikcie, takže presnosť je poctivý odhad pre novú firmu.
Každá hodnota sa navyše porovná s oficiálnou XBRL hodnotou → stĺpec `data_check`.

## 6. Rozšírenie o ďalšie odvetvia
- **V aplikácii:** karta *Spracovať firmy → Pridať spoločnosť do katalógu* (aj nové odvetvie).
- **V súbore:** doplň riadok do `catalog/companies.csv` (`sector,subsector,ticker,name,cik`); CIK sa dohľadá automaticky zo SEC.
- **Stĺpec `cik`** sa vypĺňa len vtedy, keď firma zmenila právnu štruktúru a staršie výkazy podával iný
  emitent. Príklad: ExxonMobil sa v roku 2026 reorganizoval do holdingu – ticker XOM teraz patrí
  *ExxonMobil Holdings Corp* (CIK 2115436), výkazy do roku 2025 sú pod *Exxon Mobil Corp* (CIK 34088),
  preto má v katalógu `2115436;34088`. Výkazy oboch emitentov sa spoja.
- Funguje pre americké firmy, ktoré podávajú **10-K/10-Q** (nie zahraničné s 20-F).
- **Banky a poisťovne** nemajú tržby, CAPEX ani klasický dlh – pre ne by bolo treba iné metriky (čisté úrokové výnosy, CET1…). Metriky sa definujú v `src/config.py` → `METRICS`.

## 7. Zdroje dát

### USA (použité v projekte)
| Zdroj | Použitie |
|---|---|
| SEC – Ticker → CIK `https://www.sec.gov/files/company_tickers.json` | dohľadanie identifikátora firmy |
| SEC EDGAR Submissions API `https://data.sec.gov/submissions/CIK##########.json` | zoznam podaní, koniec fiškálneho roka, odvetvie (SIC) |
| SEC EDGAR Archives `https://www.sec.gov/Archives/edgar/data/<CIK>/<accession>/<doc>.htm` | samotné 10-Q / 10-K (HTML s inline XBRL) |
| SEC – Accessing EDGAR Data | pravidlá: User-Agent, 10 req/s – https://www.sec.gov/os/accessing-edgar-data |
| SEC XBRL Company Facts API `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | voliteľná krížová kontrola všetkých XBRL hodnôt firmy |
| EDGAR full-text search `https://www.sec.gov/edgar/search/` | ručné vyhľadávanie a kontrola podaní |
| Yahoo Finance cez `yfinance` (https://github.com/ranaroussi/yfinance) | denné zatváracie ceny akcií pre ocenenie |

### Južná Amerika a Ázia (nepoužité, na ďalšie rozšírenie)
| Trh | Zdroj | Poznámka |
|---|---|---|
| Brazília (Petrobras) | SEC 20-F (ročne) + 6-K; **CVM Dados Abertos** (ITR štvrťročne, DFP ročne, CSV) https://dados.cvm.gov.br | IFRS, portugalčina |
| Kolumbia (Ecopetrol) | SEC 20-F + 6-K | štvrťročne len PDF |
| Kórea | **DART Open API** https://opendart.fss.or.kr | štvrťročné výkazy cez API, IFRS |
| Japonsko | **EDINET API** | od apríla 2024 zrušené povinné štvrťročné správy, ostali polročné; štvrťročné „Kessan Tanshin“ cez TDnet |
| Čína / HK | **HKEXnews**, Shanghai Stock Exchange / cninfo | PDF, ročné a polročné; A-akcie aj štvrťročne (čínština) |

Na PDF správy je experimentálny príkaz `python main.py pdf správa.pdf --ticker PBR --report-date 2025-12-31`.

## 8. Zverejnenie aplikácie (Streamlit Community Cloud)
1. `python main.py publish` – pripraví priečinok `publish/energy-nlp-app` a zip s kódom a výsledkami
   (bez `.env`, stiahnutých výkazov a modelu).
2. Obsah priečinka nahraj do nového repozitára na GitHube.
3. Na [share.streamlit.io](https://share.streamlit.io) → *Create app* → repozitár, vetva `main`, súbor `app.py`,
   v *Advanced settings* Python 3.12 → *Deploy*. Vznikne verejný odkaz `https://<názov>.streamlit.app`.
4. Bez súboru `.env` beží aplikácia v režime len na prezeranie (bez karty *Spracovať firmy*).
5. Po novom spracovaní firiem spusti znova `publish` a nahraj zmenené súbory z `output/` na GitHub;
   aplikácia sa aktualizuje sama.

## 9. Keď niečo nesedí
- **Firma chýba vo výsledkoch:** `python main.py diagnose TICKER` vypíše, či sa výkazy stiahli,
  či nie sú poškodené (chybová stránka SEC namiesto výkazu) a koľko riadkov sa z nich spracovalo.
  Poškodené súbory sa pri ďalšom spustení stiahnu znova automaticky.
- **Nízka presnosť pri niektorom ukazovateli:** pozri `output/audit/extracted_values.csv` –
  stĺpec `source_row` ukazuje, z ktorého riadku výkazu model čítal, `gold_value` správnu hodnotu.
- **Prečo model vybral konkrétnu hodnotu:** `python main.py explain TICKER --year 2025 --q 4 --metric net_income`
  vypíše najpravdepodobnejšie riadky výkazu, ich typ výkazu, entitu (materská/dcérska firma), obdobia
  stĺpcov a hodnotu, ktorú by z nich prečítal, spolu so správnou hodnotou z XBRL.
- **Priebeh a chyby spracovania:** `output/audit/last_run.log` a `output/audit/status.json`.

## 10. Obmedzenia
- **Utility (elektrárenské holdingy – NextEra, Duke, Southern, AEP, Xcel, Dominion) zatiaľ nie sú podporované.**
  Podávajú jeden spoločný 10-K/10-Q za materskú firmu a niekoľko dcérskych spoločností s takmer rovnakými
  výkazmi a model v nich spoľahlivo nerozlíšil materskú firmu (presnosť 64–92 %). Základ riešenia
  (rozpoznanie entity výkazu) je v `src/html_parser.py`; dotiahnutie je námet na ďalší vývoj.
- **Dlhové položky** (krátkodobý dlh, úroky) firmy vykazujú veľmi rozdielne – presnosť je nižšia (70–88 %),
  preto považuj čistý dlh a ukazovatele z neho za orientačné.
- Parser predpokladá, že bežné obdobie je v **prvom stĺpci** tabuľky (štandard SEC). Odchýlky zachytí `data_check`.
- EPS za Q4 je dopočítané (aproximácia). Čistý dlh je bez lízingových záväzkov, EBITDA je približná.
- Ceny z Yahoo sú upravené o **splity akcií**, výkazy nie: ak firma akcie rozdelila (napr. NVIDIA 10:1 v roku 2024), P/E za obdobia pred splitom je skreslené.
- Silnejší model: `build_model()` v `src/model.py` možno nahradiť FinBERTom – dataset aj vyhodnotenie ostanú.

## 11. Štruktúra projektu
```
energy_nlp/
├── app.py                # Streamlit aplikácia
├── main.py               # príkazový riadok: sectors | run | add | prices | kpi | diagnose | explain | remove | publish | pdf
├── catalog/companies.csv # odvetvia a firmy (rozbaľovacie zoznamy)
├── requirements.txt, .env.example, .vscode/launch.json
└── src/
    ├── config.py         # roky, metriky a ich XBRL koncepty, cesty
    ├── catalog.py        # práca s katalógom, ticker → CIK
    ├── edgar_client.py   # SEC EDGAR API (rate limit, cache, fiškálne roky)
    ├── html_parser.py    # HTML → riadky tabuliek, jednotky, XBRL fakty
    ├── dataset.py        # weak supervision, cache spracovaných dokumentov
    ├── model.py          # TF-IDF + logistická regresia, výber hodnoty
    ├── evaluate.py       # leave-one-company-out, presnosť
    ├── kpi.py            # štvrťroky, ukazovatele, r/r, TTM, kontrola kvality
    ├── valuation.py      # ceny akcií, P/E, EV/EBITDA, výnosy, aktuálne ocenenie
    ├── pipeline.py       # celý beh (volá main.py aj app.py)
    └── pdf_reader.py     # aplikácia modelu na PDF
```
