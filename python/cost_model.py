"""
Project Yumbu - cost model for one flight.

Estimates what a single flight costs to operate, split into components,
and works out the load factor (share of seats sold) needed to break even.

Every number that is an assumption lives in DEFAULT_RATES, BUSINESS_MODELS or
data/aircraft_types.csv, so you can change it in one place and list it in the
paper's Methodology section. An airline profile (data/airlines/*.json) can
override any of the rates for one airline, e.g. if you find Kenya's real
landing fee or Jambojet's fuel price.

These defaults are rough starting values, NOT verified data. Replace them with
sourced figures before publishing.

How a flight's cost is built up
-------------------------------
  block hours   = flown distance / cruise speed + taxi-and-climb allowance
  fuel          = fuel burn per block hour * block hours * fuel price
  crew          = crew cost per block hour * block hours
  maintenance   = maintenance cost per block hour * block hours
  ownership     = monthly lease / (block hours flown per month) * block hours
  landing fee   = rate per tonne * maximum take-off mass (MTOW)
  navigation    = unit rate * (distance / 100) * sqrt(MTOW / 50)
                  (same structure as the EUROCONTROL route-charge formula)
  handling      = rate per seat (ground handling for one turnaround)
  overhead      = share of all of the above (sales, admin, IT, ...)
  per passenger = cost per passenger actually carried (payment and booking
                  fees, passenger-related charges, catering for full-service)

The first eight items do not depend on how many passengers board, so they
form the "fixed cost per flight". The last one grows with every passenger.
"""

import math

# Flights rarely follow a straight line; airways and approach paths add distance.
ROUTING_FACTOR = 1.05

# Extra block time for taxiing, take-off, climb and approach (hours).
TAXI_AND_CLIMB_HOURS = 0.4

DAYS_PER_MONTH = 30

# Rates that an airline profile can override (assumptions, EUR).
DEFAULT_RATES = {
    "fuel_price_eur_per_kg": 0.85,       # jet fuel is often dearer in Africa than in Europe
    "landing_fee_eur_per_tonne": 10.0,   # per tonne of MTOW, per landing
    "nav_unit_rate_eur": 60.0,           # route charge unit rate
    "handling_eur_per_seat": 5.0,        # ground handling per turnaround
}

# Settings that depend on how the airline operates (assumptions).
# An airline profile can override these too.
BUSINESS_MODELS = {
    "low-cost": {
        "label": "Low-cost carrier",
        "block_hours_per_day": 10.0,   # LCCs fly their aircraft more each day
        "overhead_share": 0.08,
        "cost_per_passenger_eur": 4.0,
    },
    "full-service": {
        "label": "Full-service carrier",
        "block_hours_per_day": 8.5,
        "overhead_share": 0.15,
        "cost_per_passenger_eur": 12.0,   # catering, lounges, travel-agent fees
    },
}

# Human-readable names for every rate that can be overridden, used by the menus.
RATE_LABELS = {
    "fuel_price_eur_per_kg": "Jet fuel price (EUR per kg)",
    "landing_fee_eur_per_tonne": "Landing fee (EUR per tonne MTOW)",
    "nav_unit_rate_eur": "Navigation unit rate (EUR)",
    "handling_eur_per_seat": "Ground handling (EUR per seat)",
    "block_hours_per_day": "Aircraft block hours per day",
    "overhead_share": "Overhead (share of costs, e.g. 0.08)",
    "cost_per_passenger_eur": "Cost per passenger carried (EUR)",
}


def effective_rates(model_name, overrides=None):
    """Combine the defaults, the business model and an airline's own overrides."""
    rates = dict(DEFAULT_RATES)
    rates.update({k: v for k, v in BUSINESS_MODELS[model_name].items() if k != "label"})
    for key, value in (overrides or {}).items():
        if value is not None and key in rates:
            rates[key] = float(value)
    return rates


def great_circle_km(lat1, lon1, lat2, lon2):
    """Shortest distance between two points on Earth (haversine formula)."""
    earth_radius_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def block_hours(flown_km, cruise_kmh):
    """Gate-to-gate time of one flight, in hours."""
    return flown_km / cruise_kmh + TAXI_AND_CLIMB_HOURS


def flight_costs(aircraft, great_circle_distance_km, model_name, seats, overrides=None):
    """
    Return (costs, block_hours, flown_km, rates) for one flight.

    aircraft  - one row of aircraft_types.csv as a dict
    seats     - seats actually installed (may differ from the table's typical value)
    overrides - an airline profile's own rates (any key of RATE_LABELS)
    """
    rates = effective_rates(model_name, overrides)
    flown_km = great_circle_distance_km * ROUTING_FACTOR
    hours = block_hours(flown_km, float(aircraft["cruise_kmh"]))
    mtow = float(aircraft["mtow_tonnes"])

    hours_per_month = rates["block_hours_per_day"] * DAYS_PER_MONTH
    ownership_per_hour = float(aircraft["lease_eur_per_month"]) / hours_per_month

    costs = {
        "Fuel": float(aircraft["fuel_kg_per_block_hour"]) * hours * rates["fuel_price_eur_per_kg"],
        "Crew": float(aircraft["crew_eur_per_block_hour"]) * hours,
        "Maintenance": float(aircraft["maintenance_eur_per_block_hour"]) * hours,
        "Aircraft lease": ownership_per_hour * hours,
        "Landing fee": rates["landing_fee_eur_per_tonne"] * mtow,
        "Navigation charges": rates["nav_unit_rate_eur"] * (flown_km / 100) * math.sqrt(mtow / 50),
        "Ground handling": rates["handling_eur_per_seat"] * seats,
    }
    costs["Overhead"] = rates["overhead_share"] * sum(costs.values())
    return costs, hours, flown_km, rates


def break_even_load_factor(fixed_cost, seats, fare, cost_per_passenger, cargo_revenue=0.0):
    """
    Share of seats that must be sold so that revenue covers cost.

    Profit = seats * LF * (fare - cost_per_passenger) + cargo_revenue - fixed_cost
    Setting profit to zero and solving for LF gives the formula below.
    Returns None if no load factor can work (each passenger costs more than the fare).
    """
    margin_per_passenger = fare - cost_per_passenger
    if margin_per_passenger <= 0:
        return None
    lf = (fixed_cost - cargo_revenue) / (seats * margin_per_passenger)
    return max(lf, 0.0)   # below zero means cargo alone already pays for the flight


def break_even_fare(fixed_cost, seats, load_factor, cost_per_passenger, cargo_revenue=0.0):
    """Average fare needed to break even if `load_factor` of the seats are sold."""
    passengers = seats * load_factor
    return cost_per_passenger + (fixed_cost - cargo_revenue) / passengers
