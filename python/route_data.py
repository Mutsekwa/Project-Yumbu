"""
Project Yumbu - collecting route data from the web.

Sources
-------
* OurAirports (https://ourairports.com/data/) - free, public-domain database
  of every airport: codes, coordinates, city and a link to its Wikipedia page.
  Downloaded once and kept in data/cache/.
* Wikipedia, through its official API (https://en.wikipedia.org/w/api.php).
  - An airport's "Airlines and destinations" table shows which airlines fly
    where, so it can confirm that a route exists.
  - An airline's "Fleet" table lists its aircraft and their seat counts.

Wikipedia is written by volunteers, so treat what it says as a strong hint,
not proof. Check important facts against the airline's own timetable.
Wikipedia asks automated tools to identify themselves: put your own contact
email in USER_AGENT below.
"""

import io
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests
from bs4 import BeautifulSoup

USER_AGENT = "ProjectYumbu/0.2 (student research project; contact: YOUR-EMAIL-HERE)"
WIKI_API = "https://en.wikipedia.org/w/api.php"
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

PROJECT_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_DIR / "data" / "cache"
AIRCRAFT_TYPES_CSV = PROJECT_DIR / "data" / "aircraft_types.csv"


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def normalise(text):
    """Lower-case, remove accents, footnotes like [12], and everything except letters/digits."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"\[[^\]]*\]", "", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def names_match(wanted, found):
    """True if one airline name contains the other, ignoring case and punctuation."""
    a, b = normalise(wanted), normalise(found)
    if len(a) < 3 or len(b) < 3:
        return False
    return a in b or b in a


def clean_cell(text):
    """Remove footnote markers and extra spaces from a table cell."""
    text = re.sub(r"\[[^\]]*\]", "", str(text))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Airports (OurAirports)
# ---------------------------------------------------------------------------

def load_airports():
    """Return the OurAirports table, downloading it the first time."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "airports.csv"
    if not path.exists():
        print("Downloading the airport database (about 12 MB, only needed once)...")
        response = requests.get(AIRPORTS_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def find_airports(airports, query):
    """
    Look up an airport by IATA code (e.g. NBO) or by city/name (e.g. Mombasa).
    Returns a list of matching rows (as dicts), best matches first.
    """
    query = query.strip()
    if len(query) == 3 and query.isalpha():
        exact = airports[airports["iata_code"] == query.upper()]
        if len(exact) > 0:
            return exact.to_dict("records")

    # Search by city or name, but only among airports with airline service.
    served = airports[(airports["scheduled_service"] == "yes")
                      & (airports["type"].isin(["large_airport", "medium_airport"]))
                      & (airports["iata_code"] != "")]
    q = query.lower()
    hits = served[served["municipality"].str.lower().str.contains(q, regex=False)
                  | served["name"].str.lower().str.contains(q, regex=False)]
    # Large airports first.
    hits = hits.sort_values("type")
    return hits.to_dict("records")


def airport_distance_km(a, b):
    from cost_model import great_circle_km
    return great_circle_km(float(a["latitude_deg"]), float(a["longitude_deg"]),
                           float(b["latitude_deg"]), float(b["longitude_deg"]))


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------

def wiki_api(params):
    """Call the Wikipedia API and return the JSON answer."""
    params = {**params, "format": "json", "formatversion": 2}
    response = requests.get(WIKI_API, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    time.sleep(0.5)   # be polite: no more than about two requests per second
    return response.json()


def wiki_search(query):
    """Return the title of the best-matching Wikipedia article, or None."""
    data = wiki_api({"action": "query", "list": "search", "srsearch": query, "srlimit": 1})
    results = data.get("query", {}).get("search", [])
    return results[0]["title"] if results else None


def wiki_page_html(title):
    """Return (resolved_title, html) of a Wikipedia article."""
    data = wiki_api({"action": "parse", "page": title, "prop": "text", "redirects": 1})
    if "error" in data:
        raise LookupError(f"Wikipedia has no page called '{title}'")
    return data["parse"]["title"], data["parse"]["text"]


def title_from_wikipedia_link(url):
    """'https://en.wikipedia.org/wiki/Moi_International_Airport' -> 'Moi International Airport'."""
    if not url or "/wiki/" not in url:
        return None
    return unquote(url.split("/wiki/", 1)[1]).replace("_", " ")


def tables_with_headings(html):
    """
    Yield (h2_text, h3_text, table) for every wikitable on the page, so that
    we know which section each table belongs to.
    """
    soup = BeautifulSoup(html, "html.parser")
    h2_text, h3_text = "", ""
    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name == "h2":
            h2_text, h3_text = element.get_text(" ", strip=True), ""
        elif element.name == "h3":
            h3_text = element.get_text(" ", strip=True)
        elif "wikitable" in (element.get("class") or []):
            yield h2_text, h3_text, element


# ---------------------------------------------------------------------------
# Does the airline fly this route?
# ---------------------------------------------------------------------------

def _destination_matches(cell, airport):
    """True if a 'Destinations' table cell mentions the given airport."""
    wanted_titles = {normalise(t) for t in [title_from_wikipedia_link(airport.get("wikipedia_link")),
                                            airport.get("name")] if t}
    for link in cell.find_all("a", href=True):
        href = link["href"]
        if href.startswith("/wiki/") and normalise(unquote(href[6:]).replace("_", " ")) in wanted_titles:
            return True
    # Fall back to the city name, which is how Wikipedia usually displays destinations.
    city = normalise(airport.get("municipality", ""))
    cell_parts = [normalise(part) for part in re.split(r"[,;\n]|\s–\s", cell.get_text("\n"))]
    return bool(city) and any(part == city or part.startswith(city) for part in cell_parts)


def check_route(airline_name, origin, destination):
    """
    Look for the airline flying origin -> destination in Wikipedia's
    'Airlines and destinations' tables. Checks the origin airport's page
    first, then the destination's page (for the return flight).

    Returns a dict: {"found": bool, "page": title or None, "listed_as": text, "error": text}
    """
    result = {"found": False, "page": None, "listed_as": "", "error": ""}
    for page_airport, other_airport in [(origin, destination), (destination, origin)]:
        title = title_from_wikipedia_link(page_airport.get("wikipedia_link")) or page_airport["name"]
        try:
            title, html = wiki_page_html(title)
        except (requests.RequestException, LookupError) as error:
            result["error"] = f"Could not read '{title}': {error}"
            continue

        for h2, h3, table in tables_with_headings(html):
            if "destination" not in h2.lower() or "cargo" in h3.lower():
                continue   # only the passenger destinations tables
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) < 2 or not names_match(airline_name, cells[0].get_text(" ")):
                    continue
                if _destination_matches(cells[1], other_airport):
                    result.update(found=True, page=title,
                                  listed_as=clean_cell(cells[0].get_text(" ")))
                    return result
    return result


# ---------------------------------------------------------------------------
# Which aircraft does the airline fly?
# ---------------------------------------------------------------------------

def _flatten_columns(df):
    """Turn multi-level table headers like ('Passengers', 'Total') into 'Passengers Total'."""
    names = []
    for col in df.columns:
        parts = col if isinstance(col, tuple) else (col,)
        unique = []
        for part in parts:
            part = clean_cell(part)
            if part and not part.startswith("Unnamed") and part not in unique:
                unique.append(part)
        names.append(" ".join(unique))
    df.columns = names
    return df


def parse_fleet_table(table):
    """Return a list of {"aircraft", "seats", "seats_text"} from one fleet wikitable."""
    try:
        df = pd.read_html(io.StringIO(str(table)))[0]
    except ValueError:
        return []
    df = _flatten_columns(df)
    if len(df.columns) < 2:
        return []

    aircraft_col = df.columns[0]
    seat_cols = [c for c in df.columns if re.search(r"passeng|seat|capacity", c, re.I)]
    if not seat_cols:
        return []
    totals = [c for c in seat_cols if "total" in c.lower()]
    seat_col = totals[0] if totals else seat_cols[0]

    fleet = []
    for _, row in df.iterrows():
        name = clean_cell(row[aircraft_col])
        if not name or name.lower() in ("nan", "total") or name.lower().startswith("total"):
            continue
        seats_text = clean_cell(row[seat_col])
        numbers = [int(n) for n in re.findall(r"\d+", seats_text) if 10 <= int(n) <= 900]
        fleet.append({"aircraft": name,
                      "seats": numbers[0] if numbers else None,
                      "seats_text": " / ".join(str(n) for n in numbers) or seats_text})
    # The same aircraft can appear twice when cells span several rows.
    unique = {}
    for item in fleet:
        unique.setdefault((item["aircraft"], item["seats_text"]), item)
    return list(unique.values())


def get_fleet(airline_title):
    """Return (resolved_title, fleet list) from the airline's Wikipedia 'Fleet' section."""
    title, html = wiki_page_html(airline_title)
    fleet = []
    for h2, h3, table in tables_with_headings(html):
        section = f"{h2} {h3}".lower()
        caption = table.find("caption")
        caption_text = caption.get_text(" ").lower() if caption else ""
        is_fleet = "fleet" in section or "fleet" in caption_text
        is_old = any(w in section + caption_text for w in ("former", "historic", "retired", "past"))
        if is_fleet and not is_old:
            fleet.extend(parse_fleet_table(table))
    return title, fleet


# ---------------------------------------------------------------------------
# Our own aircraft performance and cost table
# ---------------------------------------------------------------------------

def load_aircraft_types():
    return pd.read_csv(AIRCRAFT_TYPES_CSV).to_dict("records")


def match_aircraft_type(aircraft_name, aircraft_types):
    """
    Find the row of aircraft_types.csv that best matches a name such as
    'Boeing 737-800' or 'De Havilland Canada Dash 8-400'. The longest
    matching alias wins, so 'A320neo' beats 'A320'. Returns None if nothing fits.
    """
    name = normalise(aircraft_name)
    best, best_length = None, 0
    for row in aircraft_types:
        for alias in [row["code"], row["name"]] + str(row["aliases"]).split("|"):
            alias = normalise(alias)
            if len(alias) > best_length and alias in name:
                best, best_length = row, len(alias)
    return best
