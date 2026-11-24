# Roadmap

## Done
- [x] C profit calculator with cargo modes, web version with chart
- [x] Route estimator: OurAirports distances, Wikipedia route and fleet lookup, component cost model
- [x] Airline profiles: build, correct and save as default
- [x] Route list (33 routes: Kenya domestic, East Africa cross-border, Other Africa, Europe, North America, South America, Asia)
- [x] Fare collector (SerpApi + manual entry), weekly GitHub Action
- [x] Income data from the World Bank
- [x] Dashboard

## Next (December)
- [ ] Get a SerpApi key, set up the GitHub secret, run the Action once by hand
- [ ] Check every route in `data/routes.csv`: is there really a nonstop low-cost service? Replace any that aren't comparable
- [ ] Build profiles for Jambojet, Kenya Airways, Skyward Express; record sources
- [ ] Manual fare checks on airline websites for the Kenyan routes, to validate the automatic data
- [ ] Literature: read the starter list in `paper/outline.md`, one-paragraph notes per paper

## January – February
- [ ] Replace placeholder costs: Kenyan jet fuel price, KAA landing fees, KCAA navigation charges, ticket taxes (AFRAA study)
- [ ] Same values for one European LCC route (the baseline)
- [ ] Sensitivity analysis (tornado chart): which assumption moves the break-even fare most?
- [ ] Draft Introduction, Literature Review, Methodology

## Spring
- [ ] Counterfactual scenarios: Kenyan route with European fuel price / charges / taxes / utilisation, one at a time
- [ ] Results and Discussion; supervisor feedback
- [ ] GARS Junior Workshop abstract (deadline likely around March)

## Paper 2 (year 2): intra-African connectivity and SAATM
- [ ] Extend the scraper to all major African airports' destination tables → route network
- [ ] Network analysis (networkx): direct links, connections through hubs outside Africa
- [ ] Compare SAATM implementers with non-implementers
