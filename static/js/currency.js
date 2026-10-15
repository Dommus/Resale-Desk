/*
 * DISCLAIMER: AI generated script
 #
 * Cosmetic currency display.
 *
 * Templates render the currency sign server-side via {{ currency_symbol }},
 * resolved by the inject_currency context processor from the
 * "resale-desk.currency" cookie (see utilities.py). Because the sign is part
 * of the template, user-entered text (item names, bundle names, notes, ...)
 * is never rewritten. No values are converted.
 *
 * This script only saves the choice made on the Settings page and reloads
 * the page so the server can re-render with the new currency.
 */
(function () {
    'use strict';

    const COOKIE_NAME = 'resale-desk.currency';
    const COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // one year

    const select = document.getElementById('currencySelect');
    if (!select) return;

    select.addEventListener('change', () => {
        document.cookie = `${COOKIE_NAME}=${select.value}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`;
        window.location.reload();
    });
}());
