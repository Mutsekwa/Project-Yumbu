"""
Project Yumbu - airline profiles.

A profile is everything you know about one airline, stored as a small JSON
file in data/airlines/, e.g. data/airlines/jambojet.json:

    {
      "name": "Jambojet",
      "wikipedia_title": "Jambojet",
      "business_model": "low-cost",
      "source": "custom",                 # "wikipedia" or "custom" (you edited it)
      "updated": "2026-11-23",
      "fleet": [
        {"aircraft": "De Havilland Canada Dash 8-400", "cost_type": "Q400",
         "seats": 78, "belly_cargo_kg": 800, "source": "Wikipedia fleet table"}
      ],
      "cost_overrides": {"fuel_price_eur_per_kg": 0.92},
      "routes": {
        "NBO-MBA": {"flights_per_day": 6, "fare_eur": 55,
                    "fare_source": "jambojet.com, booked 21 days ahead", "checked": "2026-11-23"}
      },
      "notes": "Any sources or comments"
    }

Once a profile exists, the route tool uses it instead of Wikipedia, so every
correction you make is kept. The files are plain text: you can also open
them in any editor, and Git shows exactly what changed.
"""

import json
import re
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_DIR / "data" / "airlines"


def slug(name):
    """'Kenya Airways' -> 'kenya-airways' (used as the file name)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "airline"


def profile_path(name):
    return PROFILE_DIR / f"{slug(name)}.json"


def new_profile(name, wikipedia_title=None, business_model="low-cost"):
    return {
        "name": name,
        "wikipedia_title": wikipedia_title,
        "business_model": business_model,
        "source": "wikipedia" if wikipedia_title else "custom",
        "updated": date.today().isoformat(),
        "fleet": [],
        "cost_overrides": {},
        "routes": {},
        "notes": "",
    }


def load_profile(name):
    """Return the saved profile for this airline, or None if there isn't one."""
    path = profile_path(name)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    # Fill in any keys added in later versions of this program.
    for key, value in new_profile(name).items():
        profile.setdefault(key, value)
    return profile


def save_profile(profile):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile["updated"] = date.today().isoformat()
    path = profile_path(profile["name"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return path


def list_profiles():
    if not PROFILE_DIR.exists():
        return []
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))


def route_key(origin_code, destination_code):
    return f"{origin_code}-{destination_code}"


def describe(profile):
    """Short text summary of a profile for the terminal."""
    lines = [f"  {profile['name']}  ({profile['business_model']}, source: {profile['source']},"
             f" updated {profile['updated']})"]
    if profile["fleet"]:
        for i, a in enumerate(profile["fleet"], start=1):
            lines.append(f"    {i}. {a['aircraft']}: {a['seats']} seats, cost data {a['cost_type']}"
                         f", belly cargo {a.get('belly_cargo_kg', '?')} kg")
    else:
        lines.append("    (no aircraft yet)")
    if profile["cost_overrides"]:
        lines.append("    Own cost rates: " + ", ".join(f"{k}={v}" for k, v in profile["cost_overrides"].items()))
    if profile["routes"]:
        lines.append("    Saved routes: " + ", ".join(profile["routes"]))
    return "\n".join(lines)
