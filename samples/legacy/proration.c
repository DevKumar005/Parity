/*
 * proration.c
 *
 * Subscription proration for mid-cycle upgrades/downgrades.
 * Written by James T., 2008-11-20
 *
 * When a customer changes plan mid-billing-cycle, we prorate
 * the charge based on the number of days used out of the
 * total days in that billing month.
 *
 * All amounts in cents. Day numbers are 1-based (1 = first
 * day of the month).
 *
 * Updated 2012-02-29: fixed leap year bug (yes, really, on
 *   the day it mattered). See postmortem doc PM-0087.
 * Updated 2016-07-14: no functional changes, just reformatted
 *   to match new coding standard.
 */

/*
 * days_in_month
 *
 * Returns the number of days in the given month/year.
 * Handles leap years per the Gregorian calendar rules.
 *
 * year:   4-digit year (e.g. 2024)
 * month:  1-based month number (1 = January, 12 = December)
 *
 * Returns: number of days in that month (28–31),
 *          or 30 if month is out of range (defensive default,
 *          see incident #3302 where bad data hit prod).
 */
int days_in_month(int year, int month)
{
    /* days per month lookup — Jan is index 1 */
    static const int days_table[] = {
        0,   /* placeholder for index 0 */
        31,  /* Jan */
        28,  /* Feb — adjusted below for leap years */
        31,  /* Mar */
        30,  /* Apr */
        31,  /* May */
        30,  /* Jun */
        31,  /* Jul */
        31,  /* Aug */
        30,  /* Sep */
        31,  /* Oct */
        30,  /* Nov */
        31   /* Dec */
    };

    int is_leap;

    if (month < 1 || month > 12) {
        /* defensive: return 30 for garbage input rather than crash.
           This saved us during the data migration of 2013. */
        return 30;
    }

    if (month != 2)
        return days_table[month];

    /* Leap year: divisible by 4, except centuries, unless
       also divisible by 400. Same logic since the 2012 fix. */
    is_leap = (year % 4 == 0 && (year % 100 != 0 || year % 400 == 0));

    return is_leap ? 29 : 28;
}

/*
 * prorate_charge
 *
 * Calculates the prorated charge for a partial month of service.
 *
 * monthly_cents:  the full monthly charge in cents
 * start_day:      first day of usage (1-based, inclusive)
 * end_day:        last day of usage (1-based, inclusive)
 * year:           the billing year
 * month:          the billing month (1–12)
 *
 * Returns: prorated charge in cents
 *
 * The formula is:
 *   prorated = monthly_cents * days_used / days_in_month
 *
 * where days_used = end_day - start_day + 1.
 *
 * Integer division truncates toward zero — for billing this
 * means we slightly undercharge on partial months, which
 * finance approved ("better to leave a penny on the table
 * than to over-bill and deal with disputes" — CFO, 2009).
 *
 * NOTE: If start_day > end_day, days_used goes negative.
 *       The caller (Java service layer) is responsible for
 *       validation. We just do the math here.
 */
int prorate_charge(int monthly_cents, int start_day, int end_day,
                   int year, int month)
{
    int total_days;
    int days_used;

    total_days = days_in_month(year, month);

    /* Avoid division by zero — shouldn't happen with valid months,
       but we had a scare with month=0 in staging once */
    if (total_days <= 0)
        return 0;

    days_used = end_day - start_day + 1;

    /*
     * Prorate: (monthly_cents * days_used) / total_days
     *
     * C integer division truncates toward zero, so:
     *   positive / positive = floor (truncates down)
     *   negative / positive = truncates toward zero (rounds up
     *     in magnitude), which differs from Python's // operator
     *     that always floors toward negative infinity.
     *
     * For normal billing (positive values) this doesn't matter.
     * For credit adjustments (negative monthly_cents), the
     * truncation means we give slightly less credit than a
     * floor-division language would. Finance is OK with this.
     */
    return (monthly_cents * days_used) / total_days;
}
