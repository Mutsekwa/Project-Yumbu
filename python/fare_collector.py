"""
Project Yumbu - fare collector.

Records the cheapest one-way fare on every route in data/routes.csv and
appends it to data/fares/fares.csv. Run it every week (by hand, or
automatically with the GitHub Action in .github/workflows/collect-fares.yml)
and you build a time series of real fares for the paper.

Where the prices come from
--------------------------
SerpApi's Google Flights API (https://serpapi.com/google-flights-api).
Its free plan allows 250 searches a month. With 33 routes and two booking
horizons (14 and 45 days ahead) one weekly run uses 66 searches, so one key
covers three weekly runs a month. Add more keys for more searches:
SERPAPI_KEY, SERPAPI_KEY_2, SERPAPI_KEY_3 ... (up to SERPAPI_KEY_9).
The script uses each key until it runs out, then moves on to the next one.

Before every run it asks SerpApi how many searches each key has left (the
Account API is free and does not use a search), so it never goes over the
limit. Usage is also logged in data/fares/api_usage.csv, which stores only a
short fingerprint of each key, never the key itself.

Every standard search uses the same settings (one-way, economy, one adult,
prices in USD, US point of sale, Google's "deep search" with all flights shown)
so that fares are comparable between routes and weeks. Write that in the
Methodology section.

What is recorded for each search
--------------------------------
* data/fares/fares.csv: one row per search: cheapest fare overall, cheapest
  nonstop fare, median nonstop fare, how many nonstop flights and airlines
  there are (a measure of competition), and the cheapest fare of the route's
  low-cost airline (column `lcc_min_usd`), plus whether that airline was
  listed at all (`lcc_listed`). If it isn't, Google Flights may not sell it;
  check by hand before trusting that route.
* data/fares/carrier_fares.csv: the cheapest fare of every airline on the route.
* data/raw/: the full search result, compressed, so you can extract things
  later without paying for the search again. API keys are removed first.

Departure dates rotate through the days of the week from one week to the next,
so results aren't tied to the weekday the job runs on. The nominal booking
horizon (14 or 45 days) is in `horizon`; the exact gap is in `days_ahead`.

Extra checks (each uses searches; the GitHub Action runs them monthly):
    return tickets:      python python/fare_collector.py --trip return --days 30
    Kenyan point of sale: python python/fare_collector.py --gl ke --days 14 --routes NBO-MBA,NBO-KIS
    sample to verify by hand: python python/fare_collector.py --validate

You can also type in fares you checked yourself on an airline's website:
    python python/fare_collector.py --manual

Usage
-----
    set the key once:   export SERPAPI_KEY=your_key      (Windows: set SERPAPI_KEY=your_key)
    a second key:       export SERPAPI_KEY_2=your_other_key
    collect:            python python/fare_collector.py
    only some routes:   python python/fare_collector.py --routes NBO-MBA,STN-DUB
    see what you have:  python python/fare_collector.py --summary
    type a fare in:     python python/fare_collector.py --manual
"""

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
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
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"   # free, doesn't use a search
MONTHLY_LIMIT = 245          # per key: stay just under the free plan's 250 searches
SAFETY_MARGIN = 5            # searches kept in reserve on each key
DEFAULT_DAYS_AHEAD = [14, 45]

CARRIER_CSV = PROJECT_DIR / "data" / "fares" / "carrier_fares.csv"
RAW_DIR = PROJECT_DIR / "data" / "raw"

FARE_FIELDS = ["observed_on", "route_id", "origin", "destination",
               "trip_type", "point_of_sale", "horizon",
               "departure_date", "departure_weekday", "return_date", "days_ahead",
               "cheapest_usd", "cheapest_airlines", "cheapest_stops",
               "nonstop_usd", "nonstop_airlines", "nonstop_median_usd",
               "nonstop_options", "nonstop_carriers", "carriers_listed",
               "lcc", "lcc_listed", "lcc_min_usd", "lcc_nonstop",
               "typical_low_usd", "typical_high_usd",
               "distance_km", "source", "raw_file", "notes"]
CARRIER_FIELDS = ["observed_on", "route_id", "trip_type", "point_of_sale", "horizon",
                  "departure_date", "days_ahead", "airline",
                  "nonstop_options", "min_nonstop_usd", "min_any_usd"]


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


def normalise_fare_row(row):
    """Fill in columns added in later versions, so old and new rows can be analysed together."""
    if not row.get("trip_type"):
        row["trip_type"] = "one_way"
    if not row.get("point_of_sale") and row.get("source") == "serpapi_google_flights":
        row["point_of_sale"] = "us"
    if not row.get("horizon"):
        row["horizon"] = row.get("days_ahead", "")
    if not row.get("departure_weekday") and row.get("departure_date"):
        try:
            row["departure_weekday"] = date.fromisoformat(row["departure_date"]).strftime("%a")
        except ValueError:
            pass
    return row


def append_rows(path, new_rows, fields, normalise=None):
    """Add rows to a CSV file, upgrading its columns if the file is from an older version."""
    if not new_rows:
        return
    rows = read_csv(path)
    old_fields = list(rows[0].keys()) if rows else []
    if old_fields == fields:
        with open(path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields, restval="", extrasaction="ignore").writerows(new_rows)
        return
    all_fields = fields + [c for c in old_fields if c not in fields]
    rows += new_rows
    if normalise:
        rows = [normalise(r) for r in rows]
    write_csv(path, rows, all_fields)


def append_fares(rows):
    append_rows(FARES_CSV, [normalise_fare_row(r) for r in rows], FARE_FIELDS, normalise_fare_row)


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

def api_keys():
    """All SerpApi keys that are set: SERPAPI_KEY, SERPAPI_KEY_2 ... SERPAPI_KEY_9, SERPAPI_KEYS."""
    names = ["SERPAPI_KEY"] + [f"SERPAPI_KEY_{i}" for i in range(2, 10)]
    keys = [os.environ.get(name, "") for name in names]
    keys += os.environ.get("SERPAPI_KEYS", "").split(",")    # optional comma-separated list
    unique = []
    for key in (k.strip() for k in keys):
        if key and key not in unique:
            unique.append(key)
    return unique


def key_id(key):
    """Short fingerprint of a key, safe to save in the repository (the key itself never is)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def read_usage():
    rows = read_csv(USAGE_CSV)
    for row in rows:
        row["key_id"] = row.get("key_id") or ""   # rows from before multi-key support have none
    return rows


def searches_this_month(kid=None, include_unlabelled=True):
    """Searches made this month according to the usage log (failed searches included)."""
    month = date.today().strftime("%Y-%m")
    total = 0
    for u in read_usage():
        if not u["date"].startswith(month):
            continue
        if kid is None or u["key_id"] == kid or (include_unlabelled and u["key_id"] == ""):
            total += int(u["searches"])
    return total


def log_usage(searches_by_key):
    rows = read_usage()
    today = date.today().isoformat()
    for kid, n in searches_by_key.items():
        if n:
            rows.append({"date": today, "key_id": kid, "searches": n})
    if rows:
        write_csv(USAGE_CSV, rows, ["date", "key_id", "searches"])


def remaining_searches(key, first_key):
    """
    How many searches this key may still use: asks SerpApi's Account API first,
    falls back to the local usage log if that doesn't answer.
    """
    try:
        info = requests.get(SERPAPI_ACCOUNT_URL, params={"api_key": key}, timeout=30).json()
        if "error" not in info and info.get("total_searches_left") is not None:
            left = int(info["total_searches_left"])
            hourly = info.get("account_rate_limit_per_hour")
            if hourly:
                left = min(left, int(hourly) - int(info.get("this_hour_searches") or 0))
            return max(left - SAFETY_MARGIN, 0), "according to SerpApi"
        if "error" in info:
            print(f"  SerpApi says: {info['error']}")
    except (requests.RequestException, ValueError):
        pass
    used = searches_this_month(key_id(key), include_unlabelled=first_key)
    return max(MONTHLY_LIMIT - used, 0), "according to the local usage log"


def search_flights(api_key, origin, destination, departure_date, return_date=None, gl="us"):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "type": 1 if return_date else 2,   # 1 = return, 2 = one-way
        "travel_class": 1,     # economy
        "adults": 1,
        "currency": "USD",
        "hl": "en",
        "gl": gl,              # point of sale: the country the search appears to come from
        "deep_search": "true", # same results as Google Flights in a browser
        "show_hidden": "true", # include the flights behind "View more flights"
        "api_key": api_key,
    }
    if return_date:
        params["return_date"] = return_date
    response = requests.get(SERPAPI_URL, params=params, timeout=90)
    data = response.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    response.raise_for_status()
    return data


def same_airline(a, b):
    """'Norwegian' matches 'Norwegian Air Shuttle', 'GOL' matches 'Gol', etc."""
    a = "".join(ch for ch in a.lower() if ch.isalnum())
    b = "".join(ch for ch in b.lower() if ch.isalnum())
    return bool(a) and bool(b) and (a in b or b in a)


def summarise_itineraries(data, lcc=""):
    """
    Turn one search result into the numbers we record.
    Returns (summary dict, list of per-airline rows), or (None, []) if no flights.
    """
    itineraries = (data.get("best_flights") or []) + (data.get("other_flights") or [])
    options = []
    for it in itineraries:
        if it.get("price") is None or not it.get("flights"):
            continue
        airlines = []
        for leg in it["flights"]:
            if leg.get("airline") and leg["airline"] not in airlines:
                airlines.append(leg["airline"])
        options.append({"price": float(it["price"]), "stops": len(it["flights"]) - 1,
                        "airlines": " + ".join(airlines), "airline_list": airlines})
    if not options:
        return None, []

    cheapest = min(options, key=lambda o: o["price"])
    nonstops = [o for o in options if o["stops"] == 0]
    nonstop = min(nonstops, key=lambda o: o["price"], default=None)
    carriers = sorted({a for o in options for a in o["airline_list"]})
    nonstop_carriers = sorted({o["airlines"] for o in nonstops})

    # The route's low-cost airline: is it listed at all, and what does it charge?
    lcc_options = [o for o in options if lcc and all(same_airline(lcc, a) for a in o["airline_list"])]
    lcc_listed = any(same_airline(lcc, a) for a in carriers) if lcc else None
    lcc_nonstops = [o for o in lcc_options if o["stops"] == 0]
    lcc_best = min(lcc_nonstops or lcc_options, key=lambda o: o["price"], default=None)

    insights = data.get("price_insights") or {}
    typical = insights.get("typical_price_range") or ["", ""]
    summary = {
        "cheapest_usd": cheapest["price"], "cheapest_airlines": cheapest["airlines"],
        "cheapest_stops": cheapest["stops"],
        "nonstop_usd": nonstop["price"] if nonstop else "",
        "nonstop_airlines": nonstop["airlines"] if nonstop else "",
        "nonstop_median_usd": statistics.median(o["price"] for o in nonstops) if nonstops else "",
        "nonstop_options": len(nonstops), "nonstop_carriers": len(nonstop_carriers),
        "carriers_listed": "; ".join(carriers),
        "lcc": lcc,
        "lcc_listed": "" if lcc_listed is None else ("yes" if lcc_listed else "no"),
        "lcc_min_usd": lcc_best["price"] if lcc_best else "",
        "lcc_nonstop": ("yes" if lcc_nonstops else "no") if lcc_best else "",
        "typical_low_usd": typical[0], "typical_high_usd": typical[1],
    }

    # Cheapest fare of every airline (or airline combination) on this search.
    per_airline = {}
    for o in options:
        entry = per_airline.setdefault(o["airlines"], {"nonstop": [], "any": []})
        entry["any"].append(o["price"])
        if o["stops"] == 0:
            entry["nonstop"].append(o["price"])
    carrier_rows = [{"airline": name, "nonstop_options": len(v["nonstop"]),
                     "min_nonstop_usd": min(v["nonstop"]) if v["nonstop"] else "",
                     "min_any_usd": min(v["any"])} for name, v in sorted(per_airline.items())]
    return summary, carrier_rows


def save_raw(data, keys, observed_on, name):
    """Keep the full search result (compressed) so it can be re-analysed later for free."""
    clean = {k: v for k, v in data.items() if k not in ("search_metadata",)}
    if "search_parameters" in clean:
        clean["search_parameters"] = {k: v for k, v in clean["search_parameters"].items() if k != "api_key"}
    text = json.dumps(clean, ensure_ascii=False)
    if any(key in text for key in keys):     # never store a key, whatever happens
        return ""
    folder = RAW_DIR / observed_on
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(text)
    return str(path.relative_to(PROJECT_DIR))


def departure_for(today, horizon):
    """
    Departure date for a nominal horizon. Shifts by 0-6 days depending on the week
    number, so over seven weeks every weekday is sampled for each horizon.
    """
    shift = today.isocalendar()[1] % 7
    return today + timedelta(days=horizon + shift)


def collect(routes, days_ahead, max_searches, trip="one_way", gl="us"):
    keys = api_keys()
    if not keys:
        message = ("No SERPAPI_KEY found. Create a free key at serpapi.com and set it first "
                   "(see the top of this file), or use --manual.")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # In the weekly job, warn instead of failing, so that the income data and
            # distances collected in the same run are still saved.
            print(f"::warning title=No fares collected::{message} On GitHub the key must be a "
                  "repository secret named SERPAPI_KEY (Settings -> Secrets and variables -> Actions).")
            return
        sys.exit(message)

    # [key, searches it may still use]
    accounts = []
    for i, key in enumerate(keys):
        left, how = remaining_searches(key, first_key=(i == 0))
        accounts.append([key, left])
        print(f"Key {i + 1} ({key_id(key)}): {left} searches available {how}.")
    budget = min(max_searches, sum(a[1] for a in accounts))
    print(f"Searches allowed in this run: {budget}.")
    if budget <= 0:
        print("Every key has used up its searches; nothing to do.")
        return

    today = date.today()
    observed_on = datetime.now(timezone.utc).date().isoformat()
    rows, carrier_rows, used, done = [], [], {}, 0

    def search(route, departure, return_date):
        """Run one search, moving to the next key when one runs out. Returns (data, error)."""
        nonlocal done
        while done < budget:
            account = next((a for a in accounts if a[1] > 0), None)
            if account is None:
                return None, "no searches left on any key"
            kid = key_id(account[0])
            account[1] -= 1
            used[kid] = used.get(kid, 0) + 1
            done += 1
            try:
                return search_flights(account[0], route["origin"], route["destination"],
                                      departure, return_date, gl), None
            except RuntimeError as error:          # an error message from SerpApi
                text = str(error).lower()
                if "run out" in text or "limit" in text or "plan" in text:
                    print(f"  Key {kid} is out of searches ({error}); switching to the next key.")
                    account[1] = 0
                    continue
                return None, error
            except (requests.RequestException, ValueError) as error:
                return None, error
        return None, "search budget for this run used up"

    stop = False
    for route in routes:
        for horizon in days_ahead:
            dep = departure_for(today, horizon)
            departure = dep.isoformat()
            return_date = (dep + timedelta(days=7)).isoformat() if trip == "return" else ""
            days = (dep - today).days
            label = (f"{route['route_id']:<8} {departure} {dep.strftime('%a')} ({days:>2} days ahead"
                     + (", return" if return_date else "") + (f", sold in {gl.upper()}" if gl != "us" else "") + ")")
            data, error = search(route, departure, return_date or None)
            if data is None:
                print(f"  {label}: failed ({error})")
                if error in ("no searches left on any key", "search budget for this run used up"):
                    stop = True
                    break
                continue
            raw_name = f"{route['route_id']}_{trip}_{gl}_{horizon}d"
            raw_file = save_raw(data, keys, observed_on, raw_name)
            summary, per_airline = summarise_itineraries(data, route.get("typical_lcc", ""))
            if summary is None:
                print(f"  {label}: no flights found")
                continue
            common = {"observed_on": observed_on, "route_id": route["route_id"], "trip_type": trip,
                      "point_of_sale": gl, "horizon": horizon, "departure_date": departure,
                      "days_ahead": days}
            rows.append({**common, **summary,
                         "origin": route["origin"], "destination": route["destination"],
                         "departure_weekday": dep.strftime("%a"), "return_date": return_date,
                         "distance_km": route.get("distance_km", ""),
                         "source": "serpapi_google_flights", "raw_file": raw_file, "notes": ""})
            carrier_rows += [{**common, **c} for c in per_airline]
            nonstop_text = (f"nonstop ${summary['nonstop_usd']:.0f} {summary['nonstop_airlines']}"
                            if summary["nonstop_usd"] != "" else "no nonstop")
            lcc_text = ""
            if summary["lcc"]:
                lcc_text = (f", {summary['lcc']} ${summary['lcc_min_usd']:.0f}" if summary["lcc_min_usd"] != ""
                            else f", {summary['lcc']} NOT LISTED" if summary["lcc_listed"] == "no"
                            else f", {summary['lcc']} only in connections")
            print(f"  {label}: cheapest ${summary['cheapest_usd']:.0f} ({summary['cheapest_airlines']}), "
                  f"{nonstop_text}, {summary['nonstop_carriers']} nonstop airline(s){lcc_text}")
            time.sleep(1)
        if stop:
            break

    append_fares(rows)
    append_rows(CARRIER_CSV, carrier_rows, CARRIER_FIELDS)
    log_usage(used)
    missing = sorted({r["route_id"] for r in rows if r.get("lcc_listed") == "no"})
    if missing:
        print("Low-cost airline not listed by Google Flights on: " + ", ".join(missing)
              + ". Check these routes by hand (--manual).")
    print(f"Saved {len(rows)} fare(s) to {FARES_CSV.relative_to(PROJECT_DIR)}. "
          f"Searches used: " + ", ".join(f"{k} {n}" for k, n in used.items()))


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
            "trip_type": "one_way", "point_of_sale": "manual", "horizon": days,
            "departure_date": departure, "days_ahead": days,
            "cheapest_usd": price, "cheapest_airlines": airline, "cheapest_stops": stops,
            "nonstop_usd": price if stops == 0 else "", "nonstop_airlines": airline if stops == 0 else "",
            "distance_km": route.get("distance_km", ""), "source": "manual", "notes": source,
        })
    append_fares(rows)
    print(f"Saved {len(rows)} fare(s).")


def validation_sample(routes, size=6):
    """Pick fares from the latest run for you to check by hand on the airlines' own websites."""
    fares = [normalise_fare_row(f) for f in read_csv(FARES_CSV)
             if f.get("source") == "serpapi_google_flights"]
    fares = [f for f in fares if f["trip_type"] == "one_way" and f["point_of_sale"] == "us"
             and date.fromisoformat(f["departure_date"]) > date.today()]
    if not fares:
        print("No future one-way fares to check yet.")
        return
    latest = max(f["observed_on"] for f in fares)
    pool = [f for f in fares if f["observed_on"] == latest]
    kenyan = [f for f in pool if f["route_id"].startswith("NBO")]
    rng = random.Random(latest)          # same sample if you run it twice on the same data
    sample = rng.sample(kenyan, min(3, len(kenyan)))
    rest = [f for f in pool if f not in sample]
    sample += rng.sample(rest, min(size - len(sample), len(rest)))
    print(f"Check these fares (collected {latest}) on the airlines' own websites, then enter what you")
    print("find with --manual, using the same departure date. The summary then compares them.\n")
    for f in sample:
        airline = f.get("nonstop_airlines") or f["cheapest_airlines"]
        price = f.get("nonstop_usd") or f["cheapest_usd"]
        print(f"  {f['route_id']:<8} depart {f['departure_date']}: Google Flights ${float(price):.0f} ({airline})"
              + (f"; low-cost airline {f['lcc']}: ${float(f['lcc_min_usd']):.0f}" if f.get("lcc_min_usd") else ""))


def validation_report(fares):
    """Compare manual checks with API fares for the same route and departure date."""
    api = {}
    for f in fares:
        if f.get("source") == "serpapi_google_flights" and f.get("trip_type", "one_way") == "one_way":
            price = f.get("nonstop_usd") or f.get("cheapest_usd")
            if price:
                api[(f["route_id"], f["departure_date"])] = float(price)
    pairs = []
    for f in fares:
        if f.get("source") == "manual" and (f["route_id"], f["departure_date"]) in api:
            manual = float(f.get("nonstop_usd") or f["cheapest_usd"])
            pairs.append((f["route_id"], f["departure_date"], api[(f["route_id"], f["departure_date"])],
                          manual, f.get("notes", "")))
    if not pairs:
        return
    print("\nManual checks against Google Flights (same route and departure date):")
    for route_id, day, a, m, note in pairs:
        print(f"  {route_id:<8} {day}  API ${a:.0f}  manual ${m:.0f}  difference {100 * (m - a) / a:+.0f}%  ({note})")
    diffs = [abs(m - a) / a for _, _, a, m, _ in pairs]
    print(f"  Median absolute difference: {100 * statistics.median(diffs):.0f}% over {len(pairs)} checks")


def summary(routes):
    fares = read_csv(FARES_CSV)
    print(f"{len(fares)} fare observations, {searches_this_month()} API searches this month\n")
    print(f"{'Route':<9}{'Region':<26}{'km':>6}{'obs':>5}{'median $':>10}{'$ per km':>10}  latest")
    one_way = [normalise_fare_row(f) for f in fares]
    one_way = [f for f in one_way if f["trip_type"] == "one_way" and f["point_of_sale"] in ("us", "manual")]
    for r in routes:
        prices = [float(f["nonstop_usd"] or f["cheapest_usd"]) for f in one_way
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
    unlisted = sorted({f["route_id"] for f in one_way if f.get("lcc_listed") == "no"})
    if unlisted:
        print("\nLow-cost airline missing from Google Flights at least once: " + ", ".join(unlisted))
    validation_report(fares)


def main():
    parser = argparse.ArgumentParser(description="Collect airfares for Project Yumbu.")
    parser.add_argument("--routes", help="comma-separated route ids, e.g. NBO-MBA,STN-DUB")
    parser.add_argument("--days", default=",".join(map(str, DEFAULT_DAYS_AHEAD)),
                        help="booking horizons in days, e.g. 14,45")
    parser.add_argument("--max-searches", type=int, default=80, help="limit for this run")
    parser.add_argument("--manual", action="store_true", help="type in fares yourself")
    parser.add_argument("--summary", action="store_true", help="show what has been collected")
    parser.add_argument("--validate", action="store_true", help="list fares to check by hand")
    parser.add_argument("--trip", choices=["one_way", "return"], default="one_way",
                        help="return = round trip, coming back 7 days later")
    parser.add_argument("--gl", default="us", help="point of sale country code, e.g. ke")
    args = parser.parse_args()

    routes = [r for r in load_routes() if r.get("active", "yes").lower() == "yes"]
    if args.routes:
        wanted = {x.strip().upper() for x in args.routes.split(",")}
        routes = [r for r in routes if r["route_id"] in wanted]

    if args.summary:
        summary(routes)
    elif args.validate:
        validation_sample(routes)
    elif args.manual:
        manual_entry(routes)
    else:
        collect(routes, [int(d) for d in args.days.split(",")], args.max_searches,
                trip=args.trip, gl=args.gl.lower())


if __name__ == "__main__":
    main()
