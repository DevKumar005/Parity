/*
 * tiered_pricing.c
 *
 * Pricing engine for tiered/volume-based billing.
 * Originally written by Dan K., 2009-03-14
 * Ported from the VB6 billing module (see JIRA BILL-1042).
 *
 * NOTE: All monetary values are in cents to avoid floating point.
 *       Do NOT change to floats — we had rounding issues in 2007
 *       that took three sprints to fix.  —Dan
 *
 * Updated 2011-08-22: added total_with_tiers() for batch invoicing
 * Updated 2014-01-09: fixed discount_bps sign check (see incident #4471)
 */

#include <stdlib.h>

/*
 * calculate_tier_price
 *
 * Returns the total price for a given quantity at a per-unit price.
 * Both quantity and unit_price_cents should be positive.
 *
 * quantity:         number of units in this tier
 * unit_price_cents: price per unit in cents (e.g. 1999 = $19.99)
 *
 * Returns: total in cents (quantity * unit_price_cents)
 */
int calculate_tier_price(int quantity, int unit_price_cents)
{
    /* straightforward multiplication — no need for 64-bit,
       our largest tier is 50k units at $999.99 max */
    return quantity * unit_price_cents;
}

/*
 * apply_discount
 *
 * Applies a discount expressed in basis points to an amount.
 * 1 basis point = 0.01%, so 500 bps = 5.00%.
 *
 * amount_cents:  the amount before discount, in cents
 * discount_bps:  discount in basis points (0–10000)
 *
 * Returns: amount after discount, in cents
 *
 * Example: apply_discount(10000, 500) = 10000 - (10000*500/10000) = 9500
 *          i.e. $100.00 with 5% discount = $95.00
 */
int apply_discount(int amount_cents, int discount_bps)
{
    int discount;

    if (discount_bps <= 0)
        return amount_cents;

    if (discount_bps >= 10000)
        return 0;

    /* integer division truncates — this is fine for billing,
       we always round in the customer's favor */
    discount = amount_cents * discount_bps / 10000;

    return amount_cents - discount;
}

/*
 * total_with_tiers
 *
 * Calculates the total across multiple pricing tiers, then
 * applies a single discount to the combined total.
 *
 * quantities[]:   array of quantities per tier
 * prices[]:       array of unit prices (cents) per tier
 * n_items:        number of tiers (length of both arrays)
 * discount_bps:   discount in basis points applied to the sum
 *
 * Returns: discounted total in cents
 *
 * Added for the batch invoicing project, Aug 2011.
 * Max tiers per invoice is 20 (enforced in the Java layer).
 */
int total_with_tiers(int quantities[], int prices[], int n_items,
                     int discount_bps)
{
    int i;
    int running_total = 0;

    if (n_items <= 0)
        return 0;

    /* accumulate tier prices — 32-bit int is plenty,
       we never see totals above a few million cents */
    for (i = 0; i < n_items; i++) {
        running_total += calculate_tier_price(quantities[i], prices[i]);
    }

    return apply_discount(running_total, discount_bps);
}
