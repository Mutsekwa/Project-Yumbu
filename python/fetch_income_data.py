"""
Project Yumbu - income data for the affordability comparison.

Downloads GNI per capita (Atlas method, current US$; World Bank indicator
NY.GNP.PCAP.CD) for every country in data/routes.csv and writes
data/countries.csv. The dashboard uses it to express a fare as
"weeks of average income", the same measure IATA uses.

Note for the paper: GNI per capita is an average. In unequal countries the
median person earns much less, so this measure understates how expensive
flying is for most people. Say so in the Limitations section.

Run:  python python/fetch_income_data.py
"""

import csv
from datetime import date
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
ROUTES_CSV = PROJECT_DIR / "data" / "routes.csv"
COUNTRIES_CSV = PROJECT_DIR / "data" / "countries.csv"
INDICATOR = "NY.GNP.PCAP.CD"
API = "https://api.worldbank.org/v2/country/{codes}/indicator/{indicator}"


def main():
    with open(ROUTES_CSV, newline="", encoding="utf-8") as f:
        routes = list(csv.DictReader(f))
    codes = sorted({r["origin_country"] for r in routes} | {r["destination_country"] for r in routes})

    url = API.format(codes=";".join(codes), indicator=INDICATOR)
    # mrnev=1: the most recent year that actually has a value, for each country
    response = requests.get(url, params={"format": "json", "mrnev": 1, "per_page": 400}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if len(payload) < 2 or payload[1] is None:
        raise SystemExit(f"Unexpected answer from the World Bank: {payload}")

    rows = []
    for record in payload[1]:
        if record.get("value") is None:
            continue
        rows.append({
            "iso2": record["country"]["id"],
            "country": record["country"]["value"],
            "gni_per_capita_usd": round(record["value"]),
            "year": record["date"],
            "indicator": f"World Bank {INDICATOR} (GNI per capita, Atlas method, current US$)",
            "retrieved_on": date.today().isoformat(),
        })
    rows.sort(key=lambda r: r["iso2"])
    with open(COUNTRIES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    missing = set(codes) - {r["iso2"] for r in rows}
    print(f"Saved {len(rows)} countries to {COUNTRIES_CSV.relative_to(PROJECT_DIR)}")
    for r in rows:
        print(f"  {r['iso2']}  {r['country']:<28} {r['gni_per_capita_usd']:>8,} USD ({r['year']})")
    if missing:
        print("No data for: " + ", ".join(sorted(missing)))


if __name__ == "__main__":
    main()
