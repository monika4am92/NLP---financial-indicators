# NLP extrakcia finančných ukazovateľov z výkazov SEC

Projekt stiahne štvrťročné (10-Q) a ročné (10-K) výkazy amerických spoločností zo SEC EDGAR,
natrénuje NLP model, ktorý v textoch výkazov nájde vybrané finančné údaje, overí jeho presnosť
a výsledok uloží do súboru output/investor_kpis.csv so štvrťročnými
a ročnými ukazovateľmi pre investorov – od výsledkov hospodárenia až po ocenenie akcie
(P/E, EV/EBITDA, FCF a dividendový výnos). Výsledky zobrazí Streamlit.

- Odvetvia a firmy sa vyberajú z katalógu catalog/companies.csv (rozbaľovací zoznam v aplikácii).
  Pripravené sú: Energetika, Čistá energia, Technológie, Zdravotníctvo, Spotrebný tovar.
- Predvolene sa spracúvajú fiškálne roky **2024 a 2025** → štvrťroky + medziročné (r/r) zmeny.
- Fiškálne roky sa riadia firmou (Apple končí v septembri, NVIDIA v januári…).

---

1. Inštalácia vo VSC

```v termináli
python -m venv .venv
.venv\Scripts\Activate.ps1          # ak to zablokuje politika: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env               # v .env doplň svoje meno a e-mail
```

`Ctrl+Shift+P` → *Python: Select Interpreter* → `.venv`.

> SEC vyžaduje, aby každý automatický klient poslal v hlavičke `User-Agent`
> meno a kontakt, a povoľuje max. 10 požiadaviek za sekundu. Bez toho vráti chybu 403. Kód to dodržiava.

2. Spustenie

```v termináli (prišla mi to ako najjednoduchšia možnosť, kde to zobraziť)
streamlit run app.py
```
Otvorí sa prehliadač. Na karte *Spracovať firmy* vyber odvetvie (alebo „Všetky odvetvia“), firmy a roky
a klikni „Stiahnuť a spracovať“. Spracovanie beží **na pozadí ako samostatný proces**


```v termináli
python main.py sectors                                   # katalóg odvetví a firiem
python main.py run --sector Energetika                   # celé odvetvie, roky 2024–2025
python main.py run --tickers XOM CVX COP --years 2024 2025
python main.py run --all                                 # všetky firmy z katalógu naraz
python main.py diagnose XOM                              # čo sa pre firmu stiahlo/spracovalo
python main.py add NUE --sector "Materiály" --name "Nucor"   # nová firma do katalógu
python main.py prices                                    # aktualizovať ceny akcií a ocenenie
python main.py kpi                                       # prepočítať ukazovatele bez nového tréningu
```
Vo VS Code sú tieto príkazy pripravené.

Výsledky sa dopĺňajú: keď spracuješ Energetiku a potom Technológie, v `investor_kpis.csv` sú obe.
Stiahnuté výkazy sa ukladajú do `data/raw/`, takže sa nesťahujú znova.

3. Výstup: `output/investor_kpis.csv`

Jeden riadok = jedna firma × jedno obdobie (Q1–Q4 a FY za celý rok). Kódovanie UTF-8 s BOM,
takže diakritika funguje aj pri otvorení v Exceli. Rovnaký súbor číta Streamlit.

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

Ako vznikajú štvrťroky
- **Výsledovka:** 10-Q uvádza priamo „Three Months Ended“ → Q1–Q3. **Q4 = rok − (Q1+Q2+Q3).** Pri EPS je to aproximácia.
- **Cash flow:** 10-Q uvádza kumulatívne od začiatku roka → Q2 = H1 − Q1, Q3 = 9M − H1, Q4 = rok − 9M.
- **Súvaha:** stav ku koncu štvrťroka.

Ocenenie a ceny akcií
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
 
V tejto chvíli ide o informatívne údaje, nie investičné odporúčanie. Odvetvové údaje sú v textovej časti MD&A – to je ďalší vhodný krok pre NLP na rozšírenie.

4. Streamlit (app.py)

| Karta | Obsah |

| **Prehľad** | 8 kľúčových ukazovateľov firmy so zmenou r/r, aktuálne ocenenie s mediánom odvetvia, tabuľka všetkých období |
| **Ocenenie** | P/E, EV/EBITDA, P/B a výnosy firiem odvetvia vedľa seba + medián odvetvia, graf |
| **Porovnanie** | firmy odvetvia vedľa seba pre zvolený ukazovateľ a obdobie |
| **Vývoj** | vývoj ukazovateľa v čase (štvrťroky alebo roky), max. 8 firiem |
| **Tabuľka** | filtrované dáta so slovenskými názvami stĺpcov + stiahnutie CSV |
| **Kvalita dát** | presnosť modelu, obdobia na kontrolu, z ktorého riadku výkazu model čítal |
| **Spracovať firmy** | výber odvetvia a firiem z rozbaľovacieho zoznamu, rokov, spustenie; aktualizácia cien; pridanie novej firmy do katalógu |


5. Ako funguje NLP model

Čo model rieši
Výkaz firmy je dlhá webová stránka so stovkami tabuliek. Model v nich hľadá 15 konkrétnych údajov
(tržby, čistý zisk, EPS, cash flow, dlh…). Ťažkosti sú dve:

- **Každá firma píše to isté inak.** Tržby sú raz „Total revenues and other income“, inde „Net sales“
  alebo „Total operating revenues“.
- **Ten istý údaj sa vo výkaze opakuje.** Čistý zisk je vo výsledovke, ale aj v cash flow, v segmentoch
  alebo v komentári manažmentu. Model musí vybrať správne miesto a správne obdobie (štvrťrok, nie celý rok).

Odkiaľ sa model učí (bez ručného označovania)
Americký regulátor SEC vyžaduje, aby každé číslo vo výkaze malo skrytú „nálepku“ (XBRL), ktorá hovorí,
čo znamená – napr. `NetIncomeLoss` = čistý zisk. Projekt tieto nálepky používa **len ako učiteľa**:

1. Každá tabuľka sa rozloží na riadky. Pri každom riadku sa zapíše jeho **popis**, **čísla**,
   **jednotky** (milióny, tisíce) a **text nad tabuľkou** (napr. „Consolidated Statement of Cash Flows“).
2. Ak má číslo v riadku nálepku hľadaného údaju – a sedí aj obdobie a patrí celej firme, nie segmentu –
   riadok dostane označenie, napr. *čistý zisk*. Všetky ostatné riadky sú *iné*.
3. Pri čítaní model **nálepky nevidí**, len text. Preto ho možno použiť aj na dokumenty bez nálepiek
   (PDF výročné správy, zahraničné firmy).

Označenia vznikajú automaticky, takže **pridanie ďalších firiem či odvetví nestojí žiadnu prácu navyše**.
Model sa vždy učí zo všetkých doteraz stiahnutých výkazov.

Ako model rozhoduje (`src/model.py`)
- **Z čoho vychádza:** slová v popise riadku, ich časti (aby spoznal „earning“ aj „earnings“), text nad
  tabuľkou a okolie riadku – nadpis sekcie, susedné riadky, typ výkazu a veľkosť čísla. Vďaka okoliu odlíši
  napr. riadok „Diluted“ pod „Earnings per share“ (zisk na akciu) od „Diluted“ pod „Weighted-average shares“
  (počet akcií).
- **Aký je to model:** logistická regresia nad váhami slov (TF-IDF) – jednoduchý, rýchly a vysvetliteľný
  klasifikátor, ktorý každému riadku priradí pravdepodobnosť pre každý z 15 údajov.
- **Ako vyberie výslednú hodnotu:** spomedzi najpravdepodobnejších riadkov uprednostní ten, ktorý
  1. má v tabuľke **správne obdobie** (pri štvrťroku stĺpec „Three Months“, nie „Nine Months“),
  2. patrí **materskej firme**, nie dcérskej,
  3. je v **správnom výkaze** – tržby a zisk vo výsledovke, investície v cash flow, dlh v súvahe,
  4. pri zisku na akciu má **2 desatinné miesta** (počet akcií ich nemá),
  5. pri čistom zisku je to zisk **pripadajúci akcionárom**, nie vrátane menšinových podielov,
  6. pri dlhu rešpektuje význam popisu („…, less current portion“ = dlhodobý dlh, „due within one year“ = krátkodobý).
- **Keď si nie je istý**, hodnotu nechá prázdnu namiesto hádania (istota pod 15 %; pri položkách, ktoré
  firma nemusí mať, napr. spätné odkupy, pod 35 %).

Ako sa meria presnosť
Každú firmu číta model, ktorý sa učil **iba na ostatných firmách** a túto nikdy nevidel
(*leave-one-company-out*). Presnosť je teda odhad, ako by model fungoval na úplne novej firme.
Každá prečítaná hodnota sa porovná s oficiálnou hodnotou zo SEC – výsledok je v stĺpci `data_check`.

6. Pridanie ďalších firiem a odvetví
- **V app:** karta *Spracovať firmy → Pridať spoločnosť do katalógu* (dá sa založiť aj nové odvetvie).
- **V súbore:** pridaj riadok do `catalog/companies.csv` (`sector,subsector,ticker,name,cik`).
  Identifikátor firmy v SEC (CIK) sa dohľadá sám.
- **Stĺpec `cik` vypĺňaj len výnimočne** – keď firma zmenila právnu štruktúru a staršie výkazy podávala pod
  iným menom. Príklad: ExxonMobil sa v roku 2026 preorganizoval do holdingu; nové výkazy sú pod
  CIK 2115436, staršie pod CIK 34088, preto má v katalógu `2115436;34088` a výkazy sa spoja.
- Funguje pre **americké firmy**, ktoré podávajú výkazy 10-K a 10-Q (nie pre zahraničné firmy s formulárom 20-F).
- **Banky a poisťovne** sledované ukazovatele nemajú (tržby, investície, klasický dlh); potrebovali by
  vlastné metriky, ktoré sa dajú doplniť v `src/config.py`.

7. Zdroje dát

USA (použité v projekte)
| Zdroj | Na čo slúži |

| [SEC – zoznam tickerov](https://www.sec.gov/files/company_tickers.json) | prevod tickera (napr. XOM) na identifikátor firmy v SEC |
| SEC EDGAR – zoznam podaní firmy (`data.sec.gov/submissions/…`) | ktoré výkazy firma podala, kedy končí jej fiškálny rok |
| SEC EDGAR – archív výkazov (`sec.gov/Archives/edgar/data/…`) | samotné výkazy 10-Q a 10-K |
| [SEC – pravidlá prístupu](https://www.sec.gov/os/accessing-edgar-data) | povinné meno a e-mail, najviac 10 požiadaviek za sekundu |
| [EDGAR – vyhľadávanie](https://www.sec.gov/edgar/search/) | ručné dohľadanie a kontrola výkazov |
| [Yahoo Finance cez yfinance](https://github.com/ranaroussi/yfinance) | denné ceny akcií pre ocenenie |

Južná Amerika a Ázia (zatiaľ nepoužité)
| Trh | Kde sú výkazy | Poznámka |

| Brazília (Petrobras) | SEC (ročný 20-F), štvrťročne [CVM Dados Abertos](https://dados.cvm.gov.br) | IFRS, portugalčina |
| Kolumbia (Ecopetrol) | SEC (20-F) | štvrťročne len PDF |
| Kórea | [DART Open API](https://opendart.fss.or.kr) | štvrťročné výkazy cez API, IFRS |
| Japonsko | EDINET, TDnet | od apríla 2024 už nie sú povinné štvrťročné správy |
| Čína / Hongkong | HKEXnews, burza v Šanghaji | PDF, často po čínsky |

Na PDF výročné správy je experimentálny príkaz `python main.py pdf sprava.pdf --ticker PBR --report-date 2025-12-31`.

9. Keď niečo nesedí
- **Firma chýba vo výsledkoch:** `python main.py diagnose TICKER` ukáže, či sa výkazy stiahli
  a koľko sa z nich podarilo spracovať. Poškodené súbory sa pri ďalšom spustení stiahnu znova.
- **Niektorá hodnota je zlá:** v `output/audit/extracted_values.csv` je pri každej hodnote riadok výkazu,
  z ktorého model čítal (`source_row`), a správna hodnota zo SEC (`gold_value`).
- **Prečo model vybral práve túto hodnotu:** `python main.py explain TICKER --year 2025 --q 4 --metric net_income`
  vypíše riadky, medzi ktorými model vyberal, a čo by z ktorého prečítal.
- **Priebeh a chyby spracovania:** súbory `output/audit/last_run.log` a `output/audit/status.json`.

10. Obmedzenia
- **Utility nie sú podporované** (NextEra, Duke, Southern, AEP, Xcel, Dominion). Podávajú jeden spoločný
  výkaz za materskú firmu a niekoľko dcérskych s takmer rovnakými tabuľkami a model v nich spoľahlivo
  nerozlíšil materskú firmu (presnosť 64–92 %). Odstránila som prozatím pre zjednodušenie práce momentálne. Je to námet na ďalší vývoj. 
- **Dlhové položky** (krátkodobý dlh, úroky) vykazujú firmy veľmi rozdielne a presnosť je nižšia (70–88 %).
  Čistý dlh a ukazovatele z neho ber ako orientačné.
- Program predpokladá, že **aktuálne obdobie je v prvom stĺpci** tabuľky (štandard SEC). Odchýlky označí `data_check`.
- **Približné výpočty:** zisk na akciu za Q4 je dopočítaný z ročného a štvrťročných, EBITDA je približná,
  čistý dlh je bez leasingov.
- Ceny akcií z Yahoo sú prepočítané pri **rozdelení akcií** (split), výkazy nie. Pri firme, ktorá akcie
  rozdelila (napr. NVIDIA 10:1 v roku 2024), je P/E za obdobia pred splitom skreslené.
- **Silnejší model:** jednoduchý model v `src/model.py` sa dá nahradiť jazykovým modelom FinBERT;
  trénovacie dáta aj meranie presnosti ostanú rovnaké. Je to ďalší námet na ďalší vývoj.

11. Štruktúra projektu
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
