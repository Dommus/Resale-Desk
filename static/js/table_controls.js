// DISCLAIMER: This script was AI generated.
// The goal was to unify and centralize multiple JS snippets used for building tables in .html files.

/*
 * Shared filtering and sorting behavior for data tables.
 *
 * This one file powers every filterable/sortable table in the app (items,
 * purchases, etc). Instead of writing separate JS for each page, every
 * table just needs a `data-sortable-table` attribute plus a few other
 * `data-*` attributes telling this script where to find things.
 *
 * Two unrelated features live here:
 *   1. FILTERING — typing in the search box or changing a dropdown reloads
 *      the page with those values added to the URL (e.g. ?q=pokemon&status=Listed).
 *      The actual filtering happens on the server; this script's job is
 *      just to build that URL and navigate to it.
 *   2. SORTING — clicking a column header re-orders the rows already on
 *      the page, entirely in the browser, with no reload needed.
 */

// Wrapping the whole file in a function that runs itself immediately (an
// "IIFE" — Immediately Invoked Function Expression) keeps every variable
// below private to this file, so it can't accidentally collide with a
// variable of the same name in some other script on the page.
(function () {
    'use strict'; // Opts into stricter error-checking (e.g. using a variable
                  // you forgot to declare becomes an error instead of a
                  // silent bug). Good habit in any plain JS file.

    // -------------------------------------------------------------
    // FILTERING
    // -------------------------------------------------------------

    // Reads every filled-in field in a <form> and turns it into a query
    // string, e.g. "q=pokemon&status=Listed". Empty fields are skipped so
    // the URL doesn't fill up with "&category=&shelf_id=" for every filter
    // the user left blank.
    function buildQueryString(form) {
        const params = new URLSearchParams(); // A built-in helper for building "key=value&key2=value2" strings safely.

        // `FormData(form)` reads every named input inside the form.
        // `.entries()` gives us each one as a [name, value] pair.
        for (const [key, value] of new FormData(form).entries()) {
            if (value) {
                params.set(key, value);
            }
        }

        return params.toString();
    }

    // Navigates the browser to this same page, with the current filters
    // attached to the URL. This is a full page reload — the server sees
    // the new URL and re-renders the table already filtered.
    function reloadWithFilters(form) {
        const queryString = buildQueryString(form);
        const url = queryString
            ? `${window.location.pathname}?${queryString}`
            : window.location.pathname; // no filters set → plain URL, no "?"

        window.location.href = url;
    }

    // Wires up one table's filter form: typing in the search box or
    // changing a dropdown triggers `reloadWithFilters`.
    function initializeFiltering(table) {
        // Each table's HTML says which <form> holds its filters via a
        // data attribute, e.g. <table data-filter-form="itemFilters">.
        const form = document.getElementById(table.dataset.filterForm);
        if (!form) return; // this table has no filter form — nothing to do

        const searchInput = form.querySelector('input[name="q"]');
        const resetButton = document.getElementById(table.dataset.resetButton);

        // --- The search box: debounce + keep focus across reloads ---
        if (searchInput) {
            let debounceTimer;

            // sessionStorage lets us leave a small note that survives a full
            // page reload (unlike a normal JS variable, which would be wiped
            // out). We use it to remember "the user was just typing in the
            // search box" so the *new* page, once loaded, can put their
            // cursor back where it was instead of leaving the box unfocused.
            const focusKey = table.dataset.searchFocusKey;

            // On page load: if our note says the user was mid-typing, restore
            // focus and put the cursor at the end of the text (rather than
            // the start, which would feel wrong while typing).
            if (focusKey && sessionStorage.getItem(focusKey) === 'true') {
                sessionStorage.removeItem(focusKey); // one-time use — clear it
                searchInput.focus();
                searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
            }

            searchInput.addEventListener('input', () => {
                if (focusKey) sessionStorage.setItem(focusKey, 'true');

                // Debounce: every keystroke cancels the previous timer and
                // starts a new 300ms countdown. The reload only actually
                // happens once the user pauses typing for 300ms — otherwise
                // typing "pokemon" would trigger 7 separate page reloads.
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => reloadWithFilters(form), 300);
            });
        }

        // --- Dropdowns: reload immediately, no debounce needed ---
        // Picking an option is already a single, deliberate action (unlike
        // typing letter by letter), so there's no "wait for a pause" step.
        form.querySelectorAll('select').forEach(select => {
            select.addEventListener('change', () => reloadWithFilters(form));
        });

        // --- Reset button: go back to the plain, unfiltered URL ---
        if (resetButton) {
            resetButton.addEventListener('click', () => {
                if (table.dataset.searchFocusKey) {
                    sessionStorage.removeItem(table.dataset.searchFocusKey);
                }
                window.location.href = window.location.pathname;
            });
        }
    }

    // -------------------------------------------------------------
    // SORTING
    // -------------------------------------------------------------

    // Compares two table cells to decide which comes first when sorting.
    // Each cell stores its raw sort value in a data attribute, e.g.
    // <td data-sort-value="18.50">€18.50</td> — we sort using that clean
    // value, not the on-screen text (which might have a "€" or commas).
    function compareCells(cellA, cellB, type, direction) {
        const valueA = cellA.dataset.sortValue || '';
        const valueB = cellB.dataset.sortValue || '';

        // For numeric columns, empty and non-numeric values are both invalid.
        // They always sink to the bottom, regardless of sort direction.
        const numberA = Number(valueA);
        const numberB = Number(valueB);
        const validA = type === 'number'
            ? valueA.trim() !== '' && Number.isFinite(numberA)
            : valueA !== '';
        const validB = type === 'number'
            ? valueB.trim() !== '' && Number.isFinite(numberB)
            : valueB !== '';

        if (!validA && validB) return 1;
        if (validA && !validB) return -1;
        if (!validA && !validB) return 0;

        if (type === 'number') {
            return direction * (numberA - numberB);
        }

        // Plain text (and dates, which are just formatted text here) are
        // compared with localeCompare, which sorts the way a human expects
        // (case-insensitive, accents handled correctly, etc) rather than
        // by raw character codes.
        return direction * valueA.localeCompare(valueB, undefined, {
            sensitivity: 'base',
            numeric: type === 'date',
        });
    }

    // Wires up one table's clickable column headers.
    function initializeSorting(table) {
        const tableBody = table.querySelector('tbody');
        const headers = [...table.querySelectorAll('th[data-sort-key]')];
        // `[...something]` turns a NodeList (what querySelectorAll returns)
        // into a real Array, so we can use array methods like .forEach on it.

        // These two variables are "remembered" between clicks thanks to
        // closures — each header's click handler below can still see and
        // update them, even though this function has already returned.
        let activeHeader = null;
        let direction = 1; // 1 = ascending, -1 = descending

        headers.forEach(header => {
            header.addEventListener('click', () => {
                // Clicking the same header again flips the direction;
                // clicking a different header starts fresh at ascending.
                direction = activeHeader === header ? direction * -1 : 1;
                activeHeader = header;

                const rows = [...tableBody.querySelectorAll('tr[data-sort-row]')];

                // Some tables have a fixed "no items found" row that should
                // never get shuffled into the middle of the sorted results.
                const pinnedBottomRow = tableBody.querySelector('[data-sort-pinned-bottom]');

                rows.sort((rowA, rowB) => compareCells(
                    rowA.cells[header.cellIndex],
                    rowB.cells[header.cellIndex],
                    header.dataset.sortType || 'text', // default to plain text comparison
                    direction,
                ));

                // Re-insert every row in its new sorted order. Moving an
                // element that's already in the document just relocates it
                // — this doesn't delete and recreate anything.
                rows.forEach(row => {
                    if (pinnedBottomRow) {
                        tableBody.insertBefore(row, pinnedBottomRow);
                    } else {
                        tableBody.appendChild(row);
                    }
                });

                // Update each header's arrow (↑/↓) and its `aria-sort`
                // attribute, which screen readers use to announce "this
                // column is now sorted ascending/descending".
                headers.forEach(currentHeader => {
                    const isActive = currentHeader === header;
                    currentHeader.setAttribute(
                        'aria-sort',
                        isActive ? (direction === 1 ? 'ascending' : 'descending') : 'none'
                    );
                    currentHeader.querySelector('.sort-indicator').textContent =
                        isActive ? (direction === 1 ? '↑' : '↓') : '';
                });
            });

            // Accessibility: someone navigating by keyboard (not a mouse)
            // can land on a header with Tab and press Enter or Space to
            // sort — same as clicking it.
            header.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault(); // stop the page from scrolling on Space
                    header.click();
                }
            });
        });
    }

    // -------------------------------------------------------------
    // Set everything up once the page has finished loading.
    // -------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-sortable-table]').forEach(table => {
            initializeFiltering(table);
            initializeSorting(table);
        });
    });
}());