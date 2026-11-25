"""
Project Yumbu - income and market data for the affordability comparison.

Downloads World Bank indicators for every country in data/routes.csv and
writes data/countries.csv:

  gni_per_capita_usd   GNI per capita, Atlas method, current US$ (NY.GNP.PCAP.CD).
                       The dashboard's "weeks of income" uses this, like IATA does.
  gni_per_capita_ppp   GNI per capita, PPP, current international $ (NY.GNP.PCAP.PP.CD).
                       Adjusts for local prices. Use it as a robustness check: if
                       Kenya's affordability gap shrinks a lot in PPP terms, say so.
  gini                 Gini index of income inequality (SI.POV.GINI). Average income
                       overstates what a typical person earns where inequality is high.
  population           Total population (SP.POP.TOTL), a rough measure of market size.

Each value has its own year column, because the latest available year differs
between countries (Gini in particular is only measured every few years).

Run:  python python/fetch_income_data.py
"""

import csv
from datetime import date
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
ROUTES_CSV = PROJECT_DIR / "data" / "routes.csv"
COUNTRIES_CSV = PROJECT_DIR / "data" / "countries.csv"
API = "https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}"

INDICATORS = {                     # column name -> World Bank indicator code
    "gni_per_capita_usd": "NY.GNP.PCAP.CD",
    "gni_per_capita_ppp": "NY.GNP.PCAP.PP.CD",
    "gini": "SI.POV.GINI",
    "population": "SP.POP.TOTL",
}


def fetch(indicator, codes):
    """Most recent non-empty value per country: {iso2: (country name, value, year)}."""
    url = API.format(codes=";".join(codes), indicator=indicator)
    response = requests.get(url, params={"format": "json", "mrnev": 1, "per_page": 400}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if len(payload) < 2 or payload[1] is None:
        raise SystemExit(f"Unexpected answer from the World Bank for {indicator}: {payload}")
    return {r["country"]["id"]: (r["country"]["value"], r["value"], r["date"])
            for r in payload[1] if r.get("value") is not None}


def main():
    with open(ROUTES_CSV, newline="", encoding="utf-8") as f:
        routes = list(csv.DictReader(f))
    codes = sorted({r["origin_country"] for r in routes} | {r["destination_country"] for r in routes})

    rows = {code: {"iso2": code, "country": ""} for code in codes}
    for column, indicator in INDICATORS.items():
        for code, (name, value, year) in fetch(indicator, codes).items():
            if code not in rows:
                continue
            rows[code]["country"] = name
            rows[code][column] = round(value, 1) if column == "gini" else round(value)
            rows[code][f"{column}_year"] = year

    fields = ["iso2", "country"]
    for column in INDICATORS:
        fields += [column, f"{column}_year"]
    fields += ["source", "retrieved_on"]
    out = []
    for code in codes:
        row = rows[code]
        row["source"] = "World Bank WDI: " + ", ".join(INDICATORS.values())
        row["retrieved_on"] = date.today().isoformat()
        out.append(row)
    with open(COUNTRIES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        writer.writerows(out)

    print(f"Saved {len(out)} countries to {COUNTRIES_CSV.relative_to(PROJECT_DIR)}")
    print(f"  {'':4}{'country':<26}{'GNI US$':>10}{'GNI PPP':>10}{'Gini':>7}")
    for r in out:
        print(f"  {r['iso2']:<4}{r['country'][:25]:<26}{r.get('gni_per_capita_usd', ''):>10}"
              f"{r.get('gni_per_capita_ppp', ''):>10}{r.get('gini', ''):>7}")
    missing = [r["iso2"] for r in out if "gni_per_capita_usd" not in r]
    if missing:
        print("No GNI data for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
