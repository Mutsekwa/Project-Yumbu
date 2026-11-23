/*
 * Project Yumbu - Milestone 1: Airline Profit Calculator (with cargo)
 *
 * Asks for basic airline and route figures, then reports revenue,
 * profit and the break-even load factor for one aircraft.
 *
 * Three operating modes:
 *   1. Passengers only
 *   2. Passengers + belly cargo (freight in the hold under the cabin)
 *   3. All-cargo freighter (no passengers)
 *
 * Model (deliberately simple, see README for its limits):
 *   passenger revenue = seats * load factor * average ticket price
 *   cargo revenue     = cargo capacity (kg) * cargo load factor * revenue per kg
 *   profit per flight = passenger revenue + cargo revenue - operating cost per flight
 *   daily profit      = profit per flight * flights per day
 *   monthly profit    = daily profit * DAYS_PER_MONTH
 *
 *   Break-even (the load factor at which profit is exactly zero):
 *     modes 1 and 2: passenger LF = (cost - cargo revenue) / (seats * ticket price)
 *     mode 3:        cargo LF     = cost / (cargo capacity * revenue per kg)
 *
 * Compile:  gcc -Wall -Wextra -std=c11 -o profit_calculator profit_calculator.c
 * Run:      ./profit_calculator
 */

#include <stdio.h>
#include <string.h>

#define NAME_LENGTH 64
#define DAYS_PER_MONTH 30

#define MODE_PASSENGERS 1
#define MODE_BELLY_CARGO 2
#define MODE_FREIGHTER 3

/* Everything the user types in. */
struct AirlineInputs {
    char name[NAME_LENGTH];
    int mode;                   /* one of the MODE_ values above */

    int seats;                  /* passenger fields (modes 1 and 2) */
    double ticket_price;        /* average revenue per passenger, in EUR */
    double load_factor;         /* stored as a fraction, e.g. 0.82 */

    double cargo_capacity_kg;   /* cargo fields (modes 2 and 3) */
    double cargo_load_factor;   /* fraction of cargo capacity filled */
    double cargo_yield;         /* revenue per kg of cargo, in EUR */

    double cost_per_flight;     /* in EUR */
    int flights_per_day;
};

/* Everything the program calculates. */
struct AirlineResults {
    double passengers_per_flight;
    double passenger_revenue;
    double cargo_kg_per_flight;
    double cargo_revenue;
    double revenue_per_flight;
    double profit_per_flight;
    double daily_profit;
    double monthly_profit;
    double break_even;          /* passenger LF (modes 1-2) or cargo LF (mode 3), as a fraction */
};

/* Throw away the rest of the current input line (e.g. after bad input). */
static void clear_input_line(void)
{
    int c;
    while ((c = getchar()) != '\n' && c != EOF) {
        /* discard */
    }
}

/* Keep asking until the user enters a whole number in [min, max]. */
static int read_int(const char *prompt, int min, int max)
{
    int value;
    for (;;) {
        printf("%s", prompt);
        if (scanf("%d", &value) == 1 && value >= min && value <= max) {
            clear_input_line();
            return value;
        }
        printf("  Please enter a whole number between %d and %d.\n", min, max);
        clear_input_line();
    }
}

/* Keep asking until the user enters a number in [min, max]. */
static double read_double(const char *prompt, double min, double max)
{
    double value;
    for (;;) {
        printf("%s", prompt);
        if (scanf("%lf", &value) == 1 && value >= min && value <= max) {
            clear_input_line();
            return value;
        }
        printf("  Please enter a number between %.2f and %.2f.\n", min, max);
        clear_input_line();
    }
}

/* Read a line of text and remove the trailing newline. */
static void read_text(const char *prompt, char *buffer, size_t size)
{
    printf("%s", prompt);
    if (fgets(buffer, (int)size, stdin) == NULL) {
        buffer[0] = '\0';
    }
    buffer[strcspn(buffer, "\n")] = '\0';
    if (buffer[0] == '\0') {
        strcpy(buffer, "Unnamed Airline");
    }
}

static int carries_passengers(int mode)
{
    return mode == MODE_PASSENGERS || mode == MODE_BELLY_CARGO;
}

static int carries_cargo(int mode)
{
    return mode == MODE_BELLY_CARGO || mode == MODE_FREIGHTER;
}

static struct AirlineInputs get_inputs(void)
{
    struct AirlineInputs in = {0};   /* start with every field set to zero */

    printf("=== Project Yumbu: Airline Profit Calculator ===\n\n");
    read_text("Airline name: ", in.name, sizeof in.name);

    printf("\nWhat does the aircraft carry?\n");
    printf("  1. Passengers only\n");
    printf("  2. Passengers + belly cargo\n");
    printf("  3. Cargo only (freighter)\n");
    in.mode = read_int("Choice: ", 1, 3);

    if (carries_passengers(in.mode)) {
        printf("\nPassengers\n");
        in.seats        = read_int("  Aircraft seats: ", 1, 900);
        in.ticket_price = read_double("  Average ticket price (EUR): ", 0.01, 100000.0);
        in.load_factor  = read_double("  Expected load factor (%): ", 0.0, 100.0) / 100.0;
    }

    if (carries_cargo(in.mode)) {
        printf("\nCargo\n");
        in.cargo_capacity_kg = read_double("  Cargo capacity per flight (kg): ", 1.0, 200000.0);
        in.cargo_load_factor = read_double("  Share of cargo capacity filled (%): ", 0.0, 100.0) / 100.0;
        in.cargo_yield       = read_double("  Revenue per kg of cargo (EUR): ", 0.01, 1000.0);
    }

    printf("\nOperations\n");
    in.cost_per_flight = read_double("  Operating cost per flight (EUR): ", 0.0, 10000000.0);
    in.flights_per_day = read_int("  Flights per day: ", 1, 24);

    return in;
}

static struct AirlineResults calculate(struct AirlineInputs in)
{
    struct AirlineResults r = {0};

    r.passengers_per_flight = in.seats * in.load_factor;
    r.passenger_revenue     = r.passengers_per_flight * in.ticket_price;
    r.cargo_kg_per_flight   = in.cargo_capacity_kg * in.cargo_load_factor;
    r.cargo_revenue         = r.cargo_kg_per_flight * in.cargo_yield;

    r.revenue_per_flight = r.passenger_revenue + r.cargo_revenue;
    r.profit_per_flight  = r.revenue_per_flight - in.cost_per_flight;
    r.daily_profit       = r.profit_per_flight * in.flights_per_day;
    r.monthly_profit     = r.daily_profit * DAYS_PER_MONTH;

    if (in.mode == MODE_FREIGHTER) {
        /* Cost must be covered by cargo alone. */
        r.break_even = in.cost_per_flight / (in.cargo_capacity_kg * in.cargo_yield);
    } else {
        /* Cargo revenue (zero in mode 1) reduces what passengers must pay for. */
        r.break_even = (in.cost_per_flight - r.cargo_revenue) / (in.seats * in.ticket_price);
        if (r.break_even < 0.0) {
            r.break_even = 0.0;   /* cargo alone already covers the flight */
        }
    }
    return r;
}

static void print_report(struct AirlineInputs in, struct AirlineResults r)
{
    /* The load factor we break even on: passenger seats or cargo space. */
    double actual_lf = (in.mode == MODE_FREIGHTER) ? in.cargo_load_factor : in.load_factor;

    printf("\n==================================================\n");
    printf("  FINANCIAL REPORT: %s\n", in.name);
    printf("==================================================\n");
    printf("  Inputs\n");
    if (carries_passengers(in.mode)) {
        printf("    Seats per aircraft          %10d\n", in.seats);
        printf("    Average ticket price        %10.2f EUR\n", in.ticket_price);
        printf("    Passenger load factor       %10.1f %%\n", in.load_factor * 100.0);
    }
    if (carries_cargo(in.mode)) {
        printf("    Cargo capacity              %10.0f kg\n", in.cargo_capacity_kg);
        printf("    Cargo load factor           %10.1f %%\n", in.cargo_load_factor * 100.0);
        printf("    Revenue per kg              %10.2f EUR\n", in.cargo_yield);
    }
    printf("    Operating cost per flight   %10.2f EUR\n", in.cost_per_flight);
    printf("    Flights per day             %10d\n", in.flights_per_day);
    printf("--------------------------------------------------\n");
    printf("  Results per flight\n");
    if (carries_passengers(in.mode)) {
        printf("    Passengers                  %10.1f\n", r.passengers_per_flight);
        printf("    Passenger revenue           %10.2f EUR\n", r.passenger_revenue);
    }
    if (carries_cargo(in.mode)) {
        printf("    Cargo carried               %10.0f kg\n", r.cargo_kg_per_flight);
        printf("    Cargo revenue               %10.2f EUR\n", r.cargo_revenue);
    }
    printf("    Total revenue               %10.2f EUR\n", r.revenue_per_flight);
    printf("    Profit                      %10.2f EUR\n", r.profit_per_flight);
    printf("  Totals\n");
    printf("    Daily profit                %10.2f EUR\n", r.daily_profit);
    printf("    Monthly profit (%d days)    %10.2f EUR\n", DAYS_PER_MONTH, r.monthly_profit);
    printf("    Break-even %-17s%10.1f %%\n",
           in.mode == MODE_FREIGHTER ? "cargo LF" : "passenger LF", r.break_even * 100.0);
    printf("--------------------------------------------------\n");

    if (r.break_even > 1.0) {
        printf("  VERDICT: Cannot break even. Even a completely\n");
        printf("  full aircraft does not cover the cost of a flight.\n");
    } else if (in.mode == MODE_BELLY_CARGO && r.break_even == 0.0) {
        printf("  VERDICT: Cargo alone covers the cost of the flight;\n");
        printf("  every passenger is profit.\n");
    } else if (r.profit_per_flight >= 0.0) {
        printf("  VERDICT: Profitable. %s load factor is %.1f points\n",
               in.mode == MODE_FREIGHTER ? "Cargo" : "Passenger",
               (actual_lf - r.break_even) * 100.0);
        printf("  above break-even.\n");
    } else {
        printf("  VERDICT: Loss-making. %s load factor must rise\n",
               in.mode == MODE_FREIGHTER ? "Cargo" : "Passenger");
        printf("  by %.1f points to break even.\n", (r.break_even - actual_lf) * 100.0);
    }
    printf("==================================================\n");
}

int main(void)
{
    struct AirlineInputs inputs = get_inputs();
    struct AirlineResults results = calculate(inputs);
    print_report(inputs, results);
    return 0;
}
