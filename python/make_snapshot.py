"""
Project Yumbu - make a self-contained snapshot of the dashboard.

Builds web/snapshot-<date>.html: the dashboard with one day's fares (and the
route and income tables) written into the page itself, so it opens from an
email attachment or a USB stick with no other files and no internet beyond
the page. Charts that need a time series or simulator runs are hidden.

Run:  python python/make_snapshot.py                 (latest collection day)
      python python/make_snapshot.py 2026-11-25      (a given day)
"""

import csv
import io
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD = PROJECT_DIR / "web" / "dashboard.html"


def read(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def main():
    fares_text = read(PROJECT_DIR / "data" / "fares" / "fares.csv")
    rows = list(csv.DictReader(io.StringIO(fares_text)))
    if not rows:
        sys.exit("No fares collected yet.")
    days = sorted({r["observed_on"] for r in rows if r.get("source") == "serpapi_google_flights"})
    day = sys.argv[1] if len(sys.argv) > 1 else days[-1]
    chosen = [r for r in rows if r["observed_on"] == day]
    if not chosen:
        sys.exit(f"No fares collected on {day}. Days available: {', '.join(days)}")

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(chosen)

    snapshot = {"date": day, "files": {
        "routes": read(PROJECT_DIR / "data" / "routes.csv"),
        "countries": read(PROJECT_DIR / "data" / "countries.csv"),
        "fares": out.getvalue(),
    }}
    # Escape "</" so that data can never close the <script> element early.
    payload = json.dumps(snapshot, ensure_ascii=False).replace("</", "<\\/")
    html = read(DASHBOARD)
    marker = "<script>\n/* ====="
    if marker not in html:
        sys.exit("Couldn't find where to insert the data in web/dashboard.html")
    html = html.replace(marker, f"<script>window.YUMBU_SNAPSHOT = {payload};</script>\n{marker}", 1)
    html = html.replace("<title>Yumbu Fare Dashboard</title>", f"<title>Yumbu Fare Snapshot {day}</title>")

    target = PROJECT_DIR / "web" / f"snapshot-{day}.html"
    target.write_text(html, encoding="utf-8")
    print(f"Saved {target.relative_to(PROJECT_DIR)} with {len(chosen)} fares from {day}")


if __name__ == "__main__":
    main()
