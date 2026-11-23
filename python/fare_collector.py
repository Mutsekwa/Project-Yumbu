"""
Project Yumbu - fare collector.

Records the cheapest one-way fare on every route in data/routes.csv and
appends it to data/fares/fares.csv. Run it every week (by hand, or
automatically with the GitHub Action in .github/workflows/collect-fares.yml)
and you build a time series of real fares for the paper.

Where the prices come from
--------------------------
SerpApi's Google Flights API (https://serpapi.com/google-flights-api).
Its free plan allows 250 searches a month. With 26 routes and two booking
horizons (14 and 45 days ahead) one weekly run uses 52 searches, so four
or five runs fit in a month. The script refuses to go over MONTHLY_LIMIT.

Every search uses the same settings (one-way, economy, one adult, prices in
USD, US point of sale) so that fares are comparable between routes and weeks.
Write that in the Methodology section.

You can also type in fares you checked yourself on an airline's website:
    python python/fare_collector.py --manual

Usage
-----
    set the key once:   export SERPAPI_KEY=your_key      (Windows: set SERPAPI_KEY=your_key)
    collect:            python python/fare_collector.py
    only some routes:   python python/fare_collector.py --routes NBO-MBA,STN-DUB
    see what you have:  python python/fare_collector.py --summary
    type a fare in:     python python/fare_collector.py --manual
"""

import argparse
import csv
import os
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).resolve().parent.parent
ROUTES_CSV = PROJECT_DIR / "data" / "routes.csv"
FARES_CSV = PROJECT_DIR / "data" / "fares" / "fares.csv"
USAGE_CSV = PROJECT_DIR / "data" / "fares" / "api_usage.csv"   # searches made per run

SERPAPI_URL = "https://serpapi.com/search.json"
MONTHLY_LIMIT = 245          # stay just under the free plan's 250 searches
DEFAULT_DAYS_AHEAD = [14, 45]

FARE_FIELDS = ["observed_on", "route_id", "origin", "destination", "departure_date", "days_ahead",
               "cheapest_usd", "cheapest_airlines", "cheapest_stops",
               "nonstop_usd", "nonstop_airlines", "typical_low_usd", "typical_high_usd",
               "distance_km", "source", "notes"]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def read_csv(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_fares(rows):
    new_file = not FARES_CSV.exists()
    FARES_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(FARES_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FARE_FIELDS, restval="")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def load_routes():
    """Read data/routes.csv and fill in any missing distances from OurAirports."""
    routes = read_csv(ROUTES_CSV)
    missing = [r for r in routes if not r.get("distance_km")]
    if missing:
        try:
            import route_data as rd
            airports = rd.load_airports()
            by_code = {a["iata_code"]: a for a in airports.to_dict("records") if a["iata_code"]}
            filled = 0
            for r in missing:
                a, b = by_code.get(r["origin"]), by_code.get(r["destination"])
                if a and b:
                    r["distance_km"] = str(round(rd.airport_distance_km(a, b)))
                    filled += 1
                else:
                    print(f"  Unknown airport code on route {r['route_id']}")
            if filled:
                with open(ROUTES_CSV, newline="", encoding="utf-8") as f:
                    fieldnames = csv.DictReader(f).fieldnames
                write_csv(ROUTES_CSV, routes, fieldnames)
                print(f"Filled in {filled} distance(s) in data/routes.csv")
        except Exception as error:   # distances are nice to have, not essential
            print(f"  Could not fill in distances ({error})")
    return routes


# ---------------------------------------------------------------------------
# SerpApi
# ---------------------------------------------------------------------------

def searches_this_month():
    """Searches made this month, from the usage log (failed searches included)."""
    month = date.today().strftime("%Y-%m")
    return sum(int(u["searches"]) for u in read_csv(USAGE_CSV) if u["date"].startswith(month))


def log_usage(searches):
    if searches == 0:
        return
    new_file = not USAGE_CSV.exists()
    USAGE_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["date", "searches"])
        writer.writerow([date.today().isoformat(), searches])


def search_one_way(api_key, origin, destination, departure_date):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "type": 2,             # one-way
        "travel_class": 1,     # economy
        "adults": 1,
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": api_key,
    }
    response = requests.get(SERPAPI_URL, params=params, timeout=90)
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    response.raise_for_status()
    return data


def summarise_itineraries(data):
    """Return the cheapest itinerary overall and the cheapest nonstop one."""
    itineraries = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = []
    for it in itineraries:
        if it.get("price") is None or not it.get("flights"):
            continue
        airlines = []
        for leg in it["flights"]:
            if leg.get("airline") and leg["airline"] not in airlines:
                airlines.append(leg["airline"])
        options.append({"price": it["price"], "stops": len(it["flights"]) - 1,
                        "airlines": " + ".join(airlines)})
    cheapest = min(options, key=lambda o: o["price"], default=None)
    nonstop = min((o for o in options if o["stops"] == 0), key=lambda o: o["price"], default=None)
    insights = data.get("price_insights") or {}
    typical = insights.get("typical_price_range") or ["", ""]
    return cheapest, nonstop, typical


def collect(routes, days_ahead, max_searches):
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        message = ("No SERPAPI_KEY found. Create a free key at serpapi.com and set it first "
                   "(see the top of this file), or use --manual.")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # In the weekly job, warn instead of failing, so that the income data and
            # distances collected in the same run are still saved.
            print(f"::warning title=No fares collected::{message} On GitHub the key must be a "
                  "repository secret named SERPAPI_KEY (Settings -> Secrets and variables -> Actions).")
            return
        sys.exit(message)

    used = searches_this_month()
    budget = min(max_searches, MONTHLY_LIMIT - used)
    print(f"Searches recorded this month: {used}. Allowed in this run: {max(budget, 0)}.")
    if budget <= 0:
        print("Monthly limit reached; nothing to do.")
        return

    today = date.today()
    observed_on = datetime.now(timezone.utc).date().isoformat()
    rows, done = [], 0
    for route in routes:
        for days in days_ahead:
            if done >= budget:
                print("Search budget for this run used up.")
                append_fares(rows)
                log_usage(done)
                return
            departure = (today + timedelta(days=days)).isoformat()
            label = f"{route['route_id']:<8} {departure} ({days:>2} days ahead)"
            try:
                data = search_one_way(api_key, route["origin"], route["destination"], departure)
            except (requests.RequestException, RuntimeError, ValueError) as error:
                print(f"  {label}: failed ({error})")
                done += 1
                continue
            done += 1
            cheapest, nonstop, typical = summarise_itineraries(data)
            if cheapest is None:
                print(f"  {label}: no flights found")
                continue
            rows.append({
                "observed_on": observed_on, "route_id": route["route_id"],
                "origin": route["origin"], "destination": route["destination"],
                "departure_date": departure, "days_ahead": days,
                "cheapest_usd": cheapest["price"], "cheapest_airlines": cheapest["airlines"],
                "cheapest_stops": cheapest["stops"],
                "nonstop_usd": nonstop["price"] if nonstop else "",
                "nonstop_airlines": nonstop["airlines"] if nonstop else "",
                "typical_low_usd": typical[0], "typical_high_usd": typical[1],
                "distance_km": route.get("distance_km", ""),
                "source": "serpapi_google_flights", "notes": "",
            })
            nonstop_text = f"nonstop ${nonstop['price']} {nonstop['airlines']}" if nonstop else "no nonstop"
            print(f"  {label}: cheapest ${cheapest['price']} ({cheapest['airlines']}), {nonstop_text}")
            time.sleep(1)
    append_fares(rows)
    log_usage(done)
    print(f"Saved {len(rows)} fare(s) to {FARES_CSV.relative_to(PROJECT_DIR)}")


# ---------------------------------------------------------------------------
# Manual entry and summary
# ---------------------------------------------------------------------------

def manual_entry(routes):
    print("Type in a fare you found yourself. Leave the route empty to stop.")
    by_id = {r["route_id"]: r for r in routes}
    print("Routes: " + ", ".join(by_id))
    rows = []
    while True:
        route_id = input("\nRoute (e.g. NBO-MBA): ").strip().upper()
        if not route_id:
            break
        if route_id not in by_id:
            print("  Not in data/routes.csv. Add it there first.")
            continue
        route = by_id[route_id]
        try:
            departure = input("  Departure date (YYYY-MM-DD): ").strip()
            days = (date.fromisoformat(departure) - date.today()).days
            price = float(input("  Cheapest one-way fare in USD: ").strip())
            airline = input("  Airline: ").strip()
            stops = int(input("  Stops (0 = nonstop): ").strip() or 0)
        except ValueError:
            print("  Couldn't read that, try again.")
            continue
        source = input("  Where did you check it? (e.g. jambojet.com): ").strip() or "manual"
        rows.append({
            "observed_on": date.today().isoformat(), "route_id": route_id,
            "origin": route["origin"], "destination": route["destination"],
            "departure_date": departure, "days_ahead": days,
            "cheapest_usd": price, "cheapest_airlines": airline, "cheapest_stops": stops,
            "nonstop_usd": price if stops == 0 else "", "nonstop_airlines": airline if stops == 0 else "",
            "distance_km": route.get("distance_km", ""), "source": "manual", "notes": source,
        })
    append_fares(rows)
    print(f"Saved {len(rows)} fare(s).")


def summary(routes):
    fares = read_csv(FARES_CSV)
    print(f"{len(fares)} fare observations, {searches_this_month()} API searches this month\n")
    print(f"{'Route':<9}{'Region':<26}{'km':>6}{'obs':>5}{'median $':>10}{'$ per km':>10}  latest")
    for r in routes:
        prices = [float(f["nonstop_usd"] or f["cheapest_usd"]) for f in fares
                  if f["route_id"] == r["route_id"] and (f["nonstop_usd"] or f["cheapest_usd"])]
        if prices:
            med = statistics.median(prices)
            km = float(r["distance_km"]) if r.get("distance_km") else None
            per_km = f"{med / km:.3f}" if km else "?"
            latest = max(f["observed_on"] for f in fares if f["route_id"] == r["route_id"])
            print(f"{r['route_id']:<9}{r['region']:<26}{r.get('distance_km', ''):>6}{len(prices):>5}"
                  f"{med:>10.0f}{per_km:>10}  {latest}")
        else:
            print(f"{r['route_id']:<9}{r['region']:<26}{r.get('distance_km', ''):>6}{0:>5}")


def main():
    parser = argparse.ArgumentParser(description="Collect airfares for Project Yumbu.")
    parser.add_argument("--routes", help="comma-separated route ids, e.g. NBO-MBA,STN-DUB")
    parser.add_argument("--days", default=",".join(map(str, DEFAULT_DAYS_AHEAD)),
                        help="booking horizons in days, e.g. 14,45")
    parser.add_argument("--max-searches", type=int, default=60, help="limit for this run")
    parser.add_argument("--manual", action="store_true", help="type in fares yourself")
    parser.add_argument("--summary", action="store_true", help="show what has been collected")
    args = parser.parse_args()

    routes = [r for r in load_routes() if r.get("active", "yes").lower() == "yes"]
    if args.routes:
        wanted = {x.strip().upper() for x in args.routes.split(",")}
        routes = [r for r in routes if r["route_id"] in wanted]

    if args.summary:
        summary(routes)
    elif args.manual:
        manual_entry(routes)
    else:
        collect(routes, [int(d) for d in args.days.split(",")], args.max_searches)


if __name__ == "__main__":
    main()
