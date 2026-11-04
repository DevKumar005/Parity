/*
 * invoice_total.c
 *
 * Tax computation and invoice totaling for US domestic invoices.
 * Written by Maria S., 2010-06-02
 *
 * All amounts in cents. Tax rates in basis points (bps).
 * 1 bps = 0.01%, so a 7.25% sales tax = 725 bps.
 *
 * IMPORTANT: We use half-up rounding for tax — this matches
 * what the tax authority expects on paper filings.
 * DO NOT CHANGE the rounding method without checking with
 * compliance (see email thread "tax rounding 2010-05-28").
 *
 * Updated 2012-11-15: added fee_cents to invoice_total() for
 *   the platform fee rollout (see BILL-2190).
 * Updated 2015-03-07: removed unused tax_exempt_flag param.
 */

/*
 * compute_tax
 *
 * Calculates the tax on an amount using half-up rounding.
 * The formula adds 5000 before dividing by 10000 so that
 * values at the midpoint (0.5 cent) round UP, which is the
 * standard commercial rounding rule.
 *
 * amount_cents:  taxable amount in cents
 * tax_rate_bps:  tax rate in basis points (e.g. 725 = 7.25%)
 *
 * Returns: tax amount in cents, half-up rounded
 *
 * Example: compute_tax(1000, 725)
 *   = (1000 * 725 + 5000) / 10000
 *   = (725000 + 5000) / 10000
 *   = 730000 / 10000
 *   = 73 cents  ($0.73 tax on $10.00 at 7.25%)
 */
int compute_tax(int amount_cents, int tax_rate_bps)
{
    /*
     * Half-up rounding: add half the divisor before integer division.
     * This rounds 0.5 up to the next integer, matching standard
     * commercial/tax rounding (as opposed to banker's rounding).
     */
    return (amount_cents * tax_rate_bps + 5000) / 10000;
}

/*
 * invoice_total
 *
 * Computes the final invoice total: subtotal + computed tax + flat fee.
 *
 * subtotal_cents:  sum of all line items in cents
 * tax_rate_bps:    applicable tax rate in basis points
 * fee_cents:       flat processing/platform fee in cents (added post-tax)
 *
 * Returns: total invoice amount in cents
 *
 * NOTE: fee_cents is not taxed — legal confirmed this for
 *       platform/service fees in all 50 states (2012-11 review).
 */
int invoice_total(int subtotal_cents, int tax_rate_bps, int fee_cents)
{
    int tax = compute_tax(subtotal_cents, tax_rate_bps);
    return subtotal_cents + tax + fee_cents;
}
