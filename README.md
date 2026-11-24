# Project Yumbu

Code and data for a research paper on airfares and affordability in Kenya:

> **Working title:** Low-Cost but Not Affordable: Decomposing the Airfare Gap Between Kenya and Mature Low-Cost Markets

**Research question:** Why are low-cost airfares in Kenya higher per kilometre than in Europe, North America and Asia, and how far could they fall if Kenya's cost disadvantages were removed?

The paper outline is in `paper/outline.md`.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/profit_calculator.c` | C profit calculator (passengers, belly cargo, freighter) |
| `web/index.html` | Interactive version of the profit calculator |
| `web/dashboard.html` | **Dashboard**: charts of fares, affordability and simulator results |
| `python/route_profitability.py` | Route profitability estimator with airline profiles |
| `python/fare_collector.py` | Weekly fare snapshots (SerpApi Google Flights) and manual fare entry |
| `python/fetch_income_data.py` | World Bank income data for the affordability measure |
| `data/routes.csv` | The 33 tracked routes: Kenya, East Africa and comparison markets |
| `data/airlines/*.json` | Airline profiles you built and corrected |
| `data/fares/fares.csv` | Collected fares |
| `data/countries.csv` | GNI per capita by country |
| `data/results/route_results.csv` | Saved runs of the route estimator |
| `data/aircraft_types.csv` | Aircraft cost assumptions (**placeholders, replace with sourced values**) |
| `.github/workflows/collect-fares.yml` | Runs the fare collector automatically every Monday |

Install the Python packages once: `pip install -r python/requirements.txt`

---

## 1. Route profitability estimator and airline profiles

```
python python/route_profitability.py
```

1. Type an airline name. If you've used it before, your **saved profile** loads. If not, the program builds one from the airline's Wikipedia fleet table.
2. Edit the profile: add or remove aircraft, fix seat counts and cargo space, switch between low-cost and full-service, and set the airline's own cost rates (fuel price, landing fee, utilisation…) with a source for each.
3. The profile is saved to `data/airlines/<airline>.json` and used by default from then on. Fares, frequencies and aircraft you enter for each route are saved too, so the next run on the same route starts from your checked values.
4. Each run is appended to `data/results/route_results.csv`.

Put your email in `USER_AGENT` in `python/route_data.py` before the first run (Wikipedia asks automated tools to identify themselves).

## 2. Fare collection

**Automatic (recommended):** prices come from [SerpApi's Google Flights API](https://serpapi.com/google-flights-api). The free plan allows 250 searches a month per key; one run covers 33 routes × 2 booking horizons (14 and 45 days ahead) = 66 searches. One key covers three weekly runs a month; with a second key (`SERPAPI_KEY_2`) every week is covered. Before each run the script asks SerpApi how many searches each key has left (this is free), uses each key until it runs out and then moves to the next. Usage is logged in `data/fares/api_usage.csv` with a short fingerprint per key, never the key itself.

```
export SERPAPI_KEY=your_key          # Windows: set SERPAPI_KEY=your_key
export SERPAPI_KEY_2=your_other_key  # optional extra keys: _2, _3 ... _9
python python/fare_collector.py      # collect now
python python/fare_collector.py --summary
```

**Manual checks** (e.g. on jambojet.com, to validate the automatic data):

```
python python/fare_collector.py --manual
```

**Every Monday without your laptop:** the GitHub Action in `.github/workflows/collect-fares.yml` runs the collector and commits the new fares to the repository.
1. On github.com: **Settings → Secrets and variables → Actions → New repository secret**, name `SERPAPI_KEY`, paste your key. Add extra keys the same way as `SERPAPI_KEY_2` and `SERPAPI_KEY_3`.
2. **Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**
3. Test it: **Actions tab → Collect fares → Run workflow.**

GitHub pauses scheduled workflows in repositories with no activity for 60 days; it emails you first, and one click re-enables it.

Settings used for every search (state these in the Methodology): one-way, economy, one adult, prices in USD, US point of sale. The dashboard uses the cheapest **nonstop** fare by default, because connecting itineraries distort fare-per-kilometre comparisons.

## 3. Income data

```
python python/fetch_income_data.py
```

Downloads GNI per capita (World Bank, Atlas method) for every country in `data/routes.csv`. The dashboard expresses a return ticket as **weeks of average income**: 2 × one-way fare ÷ (GNI per capita ÷ 52). GNI is an average, so the measure understates the burden for the typical (median) person; say so in the Limitations section.

## 4. Dashboard

`web/dashboard.html` shows fare per km by route, fare against distance, weeks of income for a return ticket, fares over time, and the simulator's break-even load factors and cost breakdown, with filters for the comparison region, booking horizon and fare type.

* **On GitHub Pages** (Settings → Pages → Deploy from branch → main → / root) it loads the CSV files automatically: `https://mutsekwa.github.io/Project-Yumbu/web/dashboard.html`
* **On your laptop:** run `python -m http.server` in the project folder and open `http://localhost:8000/web/dashboard.html`, or open the file directly and click **Load CSV files**.
* **Show demo data** fills it with clearly labelled synthetic numbers for testing. Never use those in the paper.

## 5. Profit calculator

```
gcc -Wall -Wextra -std=c11 -o profit_calculator src/profit_calculator.c
./profit_calculator
```

Three modes: passengers only, passengers + belly cargo, cargo only. `web/index.html` is the interactive version.

---

## Cost model

| Component | Formula |
| --- | --- |
| Block time | distance × 1.05 ÷ cruise speed + 0.4 h |
| Fuel | fuel burn per block hour × block time × fuel price |
| Crew, maintenance | cost per block hour × block time |
| Aircraft lease | monthly lease ÷ block hours flown per month × block time |
| Landing fee | rate × MTOW (tonnes) |
| Navigation | unit rate × (distance ÷ 100) × √(MTOW ÷ 50) |
| Ground handling | rate × seats |
| Overhead | share of all of the above |
| Per passenger | booking/payment fees, passenger charges, catering (full-service) |

Break-even load factor = (fixed cost − cargo revenue) ÷ (seats × (fare − cost per passenger)).

**⚠ Default rates in `python/cost_model.py` and `data/aircraft_types.csv` are rough placeholders.** Replace each with a sourced figure, either globally or per airline in its profile, before any result goes into the paper.

## Known limitations (for the Methodology section)

- Fare snapshots show the price offered on the day of the search, not the average fare actually paid.
- Google Flights may not list every African carrier or every fare; validate with manual checks on airline websites.
- Demand doesn't react to price in the simulator; load factor is a break-even output, not a forecast.
- Wikipedia route and fleet data are volunteer-edited and can be out of date.
- Costs are in EUR and fares in USD; convert at a stated exchange rate when combining them.
