# Data quality: weak points and how the project handles them

Things a supervisor or reviewer is likely to ask about, sorted into what the
code now handles, what needs one-off manual data, what the analysis must
handle, and what can only be stated as a limitation.

## A. Fixed in the data collection (November 2026)

| # | Problem | What could go wrong | What the code does now |
|---|---|---|---|
| A1 | Only the single cheapest flight was saved | Couldn't tell whether the low-cost airline was cheap, expensive or missing. In the first runs Jambojet was never the cheapest airline on NBO–MBA or NBO–KIS (Kenya Airways or Safarilink were) | Every airline's cheapest fare goes to `data/fares/carrier_fares.csv`. `fares.csv` records the route's low-cost airline separately (`lcc_min_usd`) and whether Google Flights listed it at all (`lcc_listed`) |
| A2 | Departure weekday tied to the day the job runs | Every observation of a horizon departed on the same weekday; weekend and weekday fares differ | Departure dates shift by 0–6 days with the week number, so all weekdays are covered over seven weeks. `horizon` is the nominal 14/45 days, `days_ahead` the exact gap, `departure_weekday` is recorded |
| A3 | Information thrown away | A later question (departure times, aircraft type, emissions) would need new searches | Every full search result is kept, compressed, in `data/raw/` (API keys removed) |
| A4 | Google's default results hide some flights | Missing cheaper or low-cost options | Searches use `deep_search` (same as the browser) and `show_hidden` ("View more flights") |
| A5 | Return fare assumed to be 2 × one-way | Full-service airlines often charge more for one-way tickets, so cross-border routes would look worse than they are | First Monday of each month: return-ticket searches on all routes (`trip_type = return`) to test the assumption |
| A6 | Prices seen from a US point of sale | Some airlines show different prices depending on where you search from | First Monday of each month: Kenyan and East African routes searched as if from Kenya (`point_of_sale = ke`) |
| A7 | No measure of competition | Fares on single-airline routes (e.g. NBO–KGL) aren't comparable with competitive routes without saying so | `nonstop_options` (flights that day) and `nonstop_carriers` (airlines) for every search |
| A8 | Average income overstates what a typical person earns | Affordability gap understated for Kenya | `countries.csv` adds PPP-adjusted income and the Gini index |
| A9 | No check against the airlines' own websites | Google Flights prices could be wrong or out of date | `fare_collector.py --validate` picks fares to check by hand; `--summary` compares your manual checks with the API |

## B. One-off manual data (templates are in the repo)

| # | Data | Why it matters | File |
|---|---|---|---|
| B1 | What each fare includes: cabin bag, checked bag, seat | A Ryanair fare without a cabin bag and a Jambojet fare with one aren't the same product. At minimum, compare "fare with one cabin bag" | `data/airlines.csv` |
| B2 | Airline type (low-cost / full-service / regional) and state ownership | The analysis needs to separate low-cost airlines from others. The pre-filled values are a first guess; verify each one | `data/airlines.csv` (`verified` column) |
| B3 | Taxes and charges in a ticket | This is central to "what explains the gap". Get a tax breakdown from a few real bookings per country | `data/taxes_charges.csv` |
| B4 | Ground alternatives (SGR train Nairobi–Mombasa, buses, ferries) | Cheap ground transport limits what airlines can charge and who flies | `data/routes.csv`, `ground_*` columns |
| B5 | Real cost inputs: Kenyan jet fuel price, KAA landing fees, aircraft lease rates | The cost model still uses placeholders | `data/aircraft_types.csv`, airline profiles |

## C. Must be handled in the analysis (no new data needed)

1. **Fare per km falls with distance.** Every flight has fixed costs (take-off, landing, turnaround), so short routes cost more per km. Comparing raw cents per km between a 200 km route (Barcelona–Palma) and a 1,000 km route (Nairobi–Mogadishu) is misleading. Instead, regress log fare on log distance with region dummies, or compare routes in the same distance band.
2. **Seasons and holidays.** December–January and July–August are peaks in Kenya; the southern hemisphere's summer is opposite to Europe's. Collect for at least six months, ideally twelve, and compare the same weeks across regions or include month effects.
3. **Repeated observations aren't independent.** Fifty snapshots of NBO–MBA are still one route. Statistical tests have to treat the route as the unit (cluster by route, or bootstrap over routes). With only six Kenyan domestic routes, report medians and ranges, not false precision.
4. **Booking horizon.** Analyse 14-day and 45-day fares separately, or include the horizon in the model.
5. **Exchange rates.** Kenyan airlines price in shillings. If the shilling weakens, fares fall in dollars without anything changing for Kenyans. Affordability should be computed in local currency or with matching exchange rates (to add: a weekly KES/USD rate).

## D. Limitations to state in the paper

- **Posted fares aren't paid fares.** Snapshots show the price offered on one day, not the average fare passengers actually paid (the airline's yield).
- **Route selection.** The comparison routes were chosen as well-known low-cost routes of similar length. That is a best case for the comparison markets. Kenya's routes are also its best-served ones, so the bias partly cancels, but say so. A rule-based sample (e.g. the busiest routes of 300–800 km in each country) would be a good robustness check if a supervisor asks.
- **Who flies.** National average income describes the typical citizen, not the typical passenger. The paper's claim concerns affordability for the population, so this is the right measure, but discuss it.
- **Google Flights coverage.** Some African airlines may sell only through their own websites. `lcc_listed` and the manual validation show how big this problem is.
- **Search budget.** A weekly run plus the monthly checks needs about 330 searches a month, more than one free SerpApi key provides.
