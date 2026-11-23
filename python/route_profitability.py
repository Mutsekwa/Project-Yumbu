"""
Project Yumbu - Route Profitability Estimator

Asks for an airline and a route, checks the route on Wikipedia, and estimates
the load factor needed to break even.

The first time you enter an airline, the program builds a profile from
Wikipedia (fleet and seat counts). You can then correct and extend it: add or
remove aircraft, fix seat counts, set the airline's own fuel price or fees.
The profile is saved in data/airlines/ and used by default from then on,
together with the fares and frequencies you entered for each route.

Run from the Project-Yumbu folder:
    pip install -r python/requirements.txt
    python python/route_profitability.py

Every run is added as a row to data/results/route_results.csv, which the
dashboard (web/dashboard.html) turns into charts.
"""

import csv
import sys
from datetime import date, datetime

import requests

import airline_profiles as ap
import cost_model as cm
import route_data as rd

RESULTS_CSV = rd.PROJECT_DIR / "data" / "results" / "route_results.csv"


# ---------------------------------------------------------------------------
# Asking questions
# ---------------------------------------------------------------------------

def ask_text(prompt, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer if answer else (default or "")


def ask_number(prompt, default=None, minimum=0.0, maximum=1e9, whole=False, allow_blank=False):
    """Keep asking until the user types a valid number. Enter accepts the default."""
    while True:
        answer = ask_text(prompt, None if default is None else f"{default:g}")
        if answer == "" and allow_blank:
            return None
        try:
            value = int(answer) if whole else float(answer)
        except ValueError:
            print(f"  Please enter a {'whole ' if whole else ''}number.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"  Please enter a value between {minimum:g} and {maximum:g}.")


def ask_yes_no(prompt, default="y"):
    while True:
        answer = ask_text(f"{prompt} (y/n)", default).lower()
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")


def ask_choice(prompt, options, default=1):
    """Show a numbered list and return the index the user picks."""
    for number, option in enumerate(options, start=1):
        print(f"  {number}. {option}")
    return ask_number(prompt, default, 1, len(options), whole=True) - 1


def heading(text):
    print(f"\n--- {text} " + "-" * max(0, 56 - len(text)))


# ---------------------------------------------------------------------------
# Building and editing an airline profile
# ---------------------------------------------------------------------------

def types_by_code(aircraft_types):
    return {t["code"]: t for t in aircraft_types}


def pick_aircraft_type(aircraft_types, prompt="  Closest type for cost data"):
    labels = [f"{t['name']} (~{t['typical_seats']} seats)" for t in aircraft_types]
    return aircraft_types[ask_choice(prompt, labels)]


def fleet_entry(aircraft_name, type_row, seats, source):
    return {"aircraft": aircraft_name, "cost_type": type_row["code"], "seats": int(seats),
            "belly_cargo_kg": float(type_row["belly_cargo_kg"]), "source": source}


def build_from_wikipedia(name, aircraft_types):
    """Create a new profile from the airline's Wikipedia article."""
    profile = ap.new_profile(name)
    try:
        title = rd.wiki_search(f"{name} airline")
    except requests.RequestException as error:
        print(f"  Could not reach Wikipedia ({error}). Starting an empty profile.")
        title = None
    if title and not ask_yes_no(f"  Use the Wikipedia article '{title}'?"):
        title = ask_text("  Exact Wikipedia article title (leave empty to skip)") or None
    profile["wikipedia_title"] = title

    fleet = []
    if title:
        try:
            title, fleet = rd.get_fleet(title)
            profile["wikipedia_title"] = title
        except (requests.RequestException, LookupError) as error:
            print(f"  Could not read the fleet from Wikipedia ({error}).")

    for item in fleet:
        match = rd.match_aircraft_type(item["aircraft"], aircraft_types)
        if match is None:
            print(f"  '{item['aircraft']}' isn't in data/aircraft_types.csv.")
            if not ask_yes_no("  Add it anyway, using the closest type's cost data?", "y"):
                continue
            match = pick_aircraft_type(aircraft_types)
        seats = item["seats"] or int(match["typical_seats"])
        profile["fleet"].append(fleet_entry(item["aircraft"], match, seats,
                                            f"Wikipedia fleet table ({title})"))
    if fleet:
        profile["source"] = "wikipedia"
        print(f"  Found {len(profile['fleet'])} aircraft type(s) on Wikipedia.")
    else:
        print("  No fleet found on Wikipedia; you can add aircraft yourself.")
        profile["source"] = "custom"

    models = list(cm.BUSINESS_MODELS)
    profile["business_model"] = models[ask_choice(
        "  Airline type", [cm.BUSINESS_MODELS[m]["label"] for m in models])]
    return profile


def edit_rates(profile):
    overrides = profile["cost_overrides"]
    while True:
        rates = cm.effective_rates(profile["business_model"], overrides)
        keys = list(cm.RATE_LABELS)
        options = []
        for key in keys:
            own = " (this airline's own)" if key in overrides else " (default)"
            options.append(f"{cm.RATE_LABELS[key]}: {rates[key]:g}{own}")
        options.append("Back")
        pick = ask_choice("  Which rate?", options, default=len(options))
        if pick == len(keys):
            return
        key = keys[pick]
        value = ask_number(f"  New value for {cm.RATE_LABELS[key]} (Enter = back to default)",
                           None, 0, 1e7, allow_blank=True)
        if value is None:
            overrides.pop(key, None)
        else:
            overrides[key] = value
            note = ask_text("  Where does this number come from? (source)")
            if note:
                profile["notes"] = (profile["notes"] + f"\n{key}: {note}").strip()


def edit_profile(profile, aircraft_types):
    """Menu for correcting and extending a profile. Returns True if anything changed."""
    changed = False
    types = types_by_code(aircraft_types)
    while True:
        print()
        print(ap.describe(profile))
        options = ["Add an aircraft", "Remove an aircraft", "Change an aircraft's seats or cargo space",
                   "Change airline type (low-cost / full-service)", "Set this airline's own cost rates",
                   "Add a note or source", "Done"]
        pick = ask_choice("  What would you like to do?", options, default=len(options))

        if pick == 0:
            type_row = pick_aircraft_type(aircraft_types, "  Aircraft type")
            name = ask_text("  Name as the airline lists it", type_row["name"])
            seats = ask_number("  Seats installed", int(type_row["typical_seats"]), 1, 900, whole=True)
            source = ask_text("  Source for this aircraft and seat count", "own research")
            profile["fleet"].append(fleet_entry(name, type_row, seats, source))
        elif pick == 1 and profile["fleet"]:
            i = ask_choice("  Remove which?", [a["aircraft"] for a in profile["fleet"]])
            profile["fleet"].pop(i)
        elif pick == 2 and profile["fleet"]:
            i = ask_choice("  Which aircraft?", [a["aircraft"] for a in profile["fleet"]])
            a = profile["fleet"][i]
            a["seats"] = ask_number("  Seats installed", a["seats"], 1, 900, whole=True)
            default_cargo = a.get("belly_cargo_kg") or float(types[a["cost_type"]]["belly_cargo_kg"])
            a["belly_cargo_kg"] = ask_number("  Belly cargo space (kg)", default_cargo, 0, 200000)
            a["source"] = ask_text("  Source", a.get("source", ""))
        elif pick == 3:
            models = list(cm.BUSINESS_MODELS)
            profile["business_model"] = models[ask_choice(
                "  Airline type", [cm.BUSINESS_MODELS[m]["label"] for m in models])]
        elif pick == 4:
            edit_rates(profile)
        elif pick == 5:
            note = ask_text("  Note")
            if note:
                profile["notes"] = (profile["notes"] + "\n" + note).strip()
        elif pick == 6:
            if changed:
                profile["source"] = "custom"
            return changed
        else:
            print("  The profile has no aircraft yet.")
            continue
        changed = True


def choose_airline(aircraft_types):
    """Load a saved profile or build a new one, let the user edit it, and save it."""
    saved = ap.list_profiles()
    if saved:
        print("  Saved airlines: " + ", ".join(saved))
    name = ""
    while not name:
        name = ask_text("Airline name (e.g. Jambojet)")

    profile = ap.load_profile(name)
    if profile:
        print("  Using your saved profile:")
        print(ap.describe(profile))
        pick = ask_choice("  Next", ["Use it as it is", "Edit it", "Rebuild it from Wikipedia"])
        if pick == 1:
            edit_profile(profile, aircraft_types)
        elif pick == 2:
            profile = build_from_wikipedia(profile["name"], aircraft_types)
            if ask_yes_no("  Edit it now?", "n"):
                edit_profile(profile, aircraft_types)
    else:
        print("  No saved profile yet, looking on Wikipedia...")
        profile = build_from_wikipedia(name, aircraft_types)
        print(ap.describe(profile))
        if ask_yes_no("  Edit this profile (add aircraft, fix seats, set the airline's own costs)?", "n"):
            edit_profile(profile, aircraft_types)

    path = ap.save_profile(profile)
    print(f"  Profile saved: {path.relative_to(ap.PROJECT_DIR)}")
    return profile


# ---------------------------------------------------------------------------
# Route and aircraft
# ---------------------------------------------------------------------------

def choose_airport(airports, prompt):
    while True:
        query = ask_text(f"{prompt} airport (IATA code like NBO, or a city)")
        matches = rd.find_airports(airports, query) if query else []
        if not matches:
            print("  No airport found, try again.")
            continue
        if len(matches) == 1:
            airport = matches[0]
        else:
            labels = [f"{m['iata_code']}  {m['name']} ({m['municipality']}, {m['iso_country']})"
                      for m in matches[:9]]
            airport = matches[ask_choice("  Which one?", labels)]
        print(f"  -> {airport['iata_code']}  {airport['name']}, {airport['municipality']}")
        return airport


def choose_aircraft(profile, aircraft_types, saved_route):
    """Return (fleet entry, cost type row). Adds a new aircraft to the profile if needed."""
    types = types_by_code(aircraft_types)
    fleet = profile["fleet"]
    options = [f"{a['aircraft']} ({a['seats']} seats)" for a in fleet] + ["Another aircraft type"]
    default = 1
    if saved_route.get("aircraft") in [a["aircraft"] for a in fleet]:
        default = [a["aircraft"] for a in fleet].index(saved_route["aircraft"]) + 1
    pick = ask_choice("  Aircraft used on this route", options, default) if fleet else len(fleet)

    if pick < len(fleet):
        entry = fleet[pick]
    else:
        type_row = pick_aircraft_type(aircraft_types, "  Aircraft type")
        seats = ask_number("  Seats installed", int(type_row["typical_seats"]), 1, 900, whole=True)
        entry = fleet_entry(type_row["name"], type_row, seats, "own research")
        if ask_yes_no("  Add this aircraft to the airline's profile?", "y"):
            fleet.append(entry)
            profile["source"] = "custom"

    seats = ask_number("  Seats installed", entry["seats"], 1, 900, whole=True)
    if seats != entry["seats"] and entry in fleet:
        if ask_yes_no("  Save the new seat count in the profile?", "y"):
            entry["seats"] = seats
            profile["source"] = "custom"
    entry = {**entry, "seats": seats}
    return entry, types[entry["cost_type"]]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def euro(amount):
    return f"EUR {amount:>10,.0f}"


def verdict(lf):
    if lf is None or lf > 1:
        return "IMPOSSIBLE at this fare: even a full aircraft loses money."
    if lf > 0.90:
        return "VERY HARD: needs almost every seat sold on every flight."
    if lf > 0.80:
        return "TIGHT: possible, but above what most airlines achieve all year."
    if lf > 0.65:
        return "ACHIEVABLE: in the range well-run airlines reach."
    return "COMFORTABLE: profitable even with many empty seats."


def run():
    print("=== Project Yumbu: Route Profitability Estimator ===")
    print("Press Enter to accept a value in [brackets].\n")

    aircraft_types = rd.load_aircraft_types()
    try:
        airports = rd.load_airports()
    except requests.RequestException as error:
        sys.exit(f"Could not download the airport database: {error}")

    heading("Airline")
    profile = choose_airline(aircraft_types)
    model = cm.BUSINESS_MODELS[profile["business_model"]]

    heading("Route")
    origin = choose_airport(airports, "From")
    destination = choose_airport(airports, "To")
    distance = rd.airport_distance_km(origin, destination)
    print(f"  Great-circle distance: {distance:,.0f} km")

    key = ap.route_key(origin["iata_code"], destination["iata_code"])
    saved_route = profile["routes"].get(key, {})
    if saved_route:
        print(f"  Using your saved values for {key} (checked {saved_route.get('checked', '?')}).")

    route = {"found": False, "page": None, "listed_as": "", "error": ""}
    print("  Checking Wikipedia's destination tables...")
    try:
        route = rd.check_route(profile["name"], origin, destination)
    except requests.RequestException as error:
        route["error"] = str(error)
    if route["found"]:
        print(f"  Route confirmed: '{route['listed_as']}' is listed on the {route['page']} page.")
    else:
        print(f"  {profile['name']} is NOT listed on this route."
              + (f" ({route['error']})" if route["error"] else ""))
        print("  You can still continue: treat it as a hypothetical new route.")
        if not ask_yes_no("  Continue?"):
            return

    flights_per_day = ask_number("  Flights per day on this route (one direction)",
                                 saved_route.get("flights_per_day", 2), 1, 50, whole=True)

    heading("Aircraft")
    print(f"  Airline type: {model['label']} (change it by editing the profile)")
    entry, aircraft = choose_aircraft(profile, aircraft_types, saved_route)
    seats = entry["seats"]

    heading("Cargo")
    cargo_revenue = 0.0
    if ask_yes_no("  Carry belly cargo alongside passengers?", "y" if saved_route.get("cargo_kg") else "n"):
        capacity = ask_number("  Cargo space available (kg)",
                              saved_route.get("cargo_kg", entry.get("belly_cargo_kg", 0)), 0, 200000)
        cargo_lf = ask_number("  Share of cargo space filled (%)",
                              saved_route.get("cargo_fill_pct", 60), 0, 100) / 100
        cargo_yield = ask_number("  Cargo revenue per kg (EUR)",
                                 saved_route.get("cargo_eur_per_kg", 1.5), 0, 100)
        cargo_revenue = capacity * cargo_lf * cargo_yield
        saved_route.update(cargo_kg=capacity, cargo_fill_pct=cargo_lf * 100, cargo_eur_per_kg=cargo_yield)
    else:
        saved_route.pop("cargo_kg", None)

    heading("Fare")
    fare = ask_number("  Average one-way fare per passenger (EUR)",
                      saved_route.get("fare_eur", 60), 1, 100000)
    fare_source = ask_text("  Where does this fare come from? (site, date, days ahead)",
                           saved_route.get("fare_source", "estimate"))

    # Remember this route's values in the airline's profile.
    saved_route.update(flights_per_day=flights_per_day, aircraft=entry["aircraft"],
                       fare_eur=fare, fare_source=fare_source, checked=date.today().isoformat())
    profile["routes"][key] = saved_route
    ap.save_profile(profile)

    # ----- Calculations -----
    costs, hours, flown_km, rates = cm.flight_costs(aircraft, distance, profile["business_model"],
                                                    seats, profile["cost_overrides"])
    fixed_cost = sum(costs.values())
    per_pax = rates["cost_per_passenger_eur"]
    lf = cm.break_even_load_factor(fixed_cost, seats, fare, per_pax, cargo_revenue)
    fare_at_80 = cm.break_even_fare(fixed_cost, seats, 0.80, per_pax, cargo_revenue)
    cask_cents = 100 * (fixed_cost + per_pax * seats * 0.8) / (seats * flown_km)

    # ----- Report -----
    print("\n" + "=" * 62)
    print(f"  ROUTE REPORT: {profile['name']}  {origin['iata_code']} -> {destination['iata_code']}")
    print("=" * 62)
    print(f"  Route            {origin['municipality']} -> {destination['municipality']}"
          f"  ({'listed on Wikipedia' if route['found'] else 'hypothetical'})")
    print(f"  Distance         {distance:,.0f} km straight line, ~{flown_km:,.0f} km flown")
    print(f"  Block time       {hours:.2f} h")
    print(f"  Aircraft         {entry['aircraft']}, {seats} seats ({model['label']})")
    if profile["cost_overrides"]:
        print(f"  Own cost rates   {', '.join(profile['cost_overrides'])}")
    print("-" * 62)
    print("  Cost of one flight (estimate)")
    for name, amount in costs.items():
        print(f"    {name:<22}{euro(amount)}   {100 * amount / fixed_cost:4.0f}%")
    print(f"    {'Fixed cost per flight':<22}{euro(fixed_cost)}")
    print(f"    {'+ per passenger':<22}{euro(per_pax)}")
    if cargo_revenue:
        print(f"    {'- cargo revenue':<22}{euro(cargo_revenue)}")
    print(f"    Cost per seat-km (at 80% full): {cask_cents:.1f} euro cents")
    print("-" * 62)
    print(f"  At an average fare of EUR {fare:,.0f}  ({fare_source}):")
    if lf is None:
        print("    Break-even load factor: none (fare is below the cost per passenger)")
    else:
        print(f"    Break-even load factor: {100 * lf:.1f} %"
              f"  = {lf * seats:.0f} of {seats} seats per flight")
        print(f"    Passengers needed per day: {lf * seats * flights_per_day:,.0f}"
              f" over {flights_per_day} flight(s)")
    print(f"  Fare needed to break even at 80% full: EUR {fare_at_80:,.0f}")
    print(f"  Daily operating cost on this route: EUR {fixed_cost * flights_per_day:,.0f}"
          " + per-passenger costs")
    print("-" * 62)
    print(f"  VERDICT: {verdict(lf)}")
    print("=" * 62)
    print("  Default costs come from rough assumptions in cost_model.py and")
    print("  data/aircraft_types.csv. Replace them with sourced figures.")

    save_result({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "airline": profile["name"], "profile_source": profile["source"],
        "business_model": profile["business_model"],
        "origin": origin["iata_code"], "destination": destination["iata_code"],
        "origin_country": origin["iso_country"], "destination_country": destination["iso_country"],
        "route_listed_on_wikipedia": route["found"],
        "distance_km": round(distance), "block_hours": round(hours, 2),
        "aircraft": entry["aircraft"], "cost_type": aircraft["code"], "seats": seats,
        "flights_per_day": flights_per_day, "fare_eur": fare, "fare_source": fare_source,
        "cargo_revenue_eur": round(cargo_revenue),
        **{f"cost_{k.lower().replace(' ', '_')}_eur": round(v) for k, v in costs.items()},
        "fixed_cost_eur": round(fixed_cost), "cost_per_passenger_eur": per_pax,
        "break_even_load_factor": None if lf is None else round(lf, 4),
        "break_even_fare_at_80pct_eur": round(fare_at_80, 2),
    })


def save_result(row):
    RESULTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(row)
    rows = []
    # If an older file has different columns, rewrite it with the union of both.
    if RESULTS_CSV.exists():
        with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            old = reader.fieldnames or []
        fieldnames = old + [c for c in fieldnames if c not in old]
    rows.append(row)
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved to {RESULTS_CSV}")


if __name__ == "__main__":
    try:
        run()
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
