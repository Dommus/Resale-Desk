/* Shared filtering and sorting behavior for data tables. */
(function () {
    'use strict';

    function buildQueryString(form) {
        const params = new URLSearchParams();

        for (const [key, value] of new FormData(form).entries()) {
            if (value) {
                params.set(key, value);
            }
        }

        return params.toString();
    }

    function reloadWithFilters(form) {
        const queryString = buildQueryString(form);
        const url = queryString
            ? `${window.location.pathname}?${queryString}`
            : window.location.pathname;
        window.location.href = url;
    }

    function compareCells(leftCell, rightCell, type) {
        const leftValue = leftCell.dataset.sortValue || '';
        const rightValue = rightCell.dataset.sortValue || '';

        // Keep missing values at the bottom in either sort direction.
        if (!leftValue && rightValue) return 1;
        if (leftValue && !rightValue) return -1;
        if (!leftValue && !rightValue) return 0;

        if (type === 'number') {
            return (Number(leftValue) - Number(rightValue)) || 0;
        }

        return leftValue.localeCompare(rightValue, undefined, {
            sensitivity: 'base',
            numeric: type === 'date',
        });
    }

    function initializeFiltering(table) {
        const form = document.getElementById(table.dataset.filterForm);
        if (!form) return;

        const searchInput = form.querySelector('input[name="q"]');
        const resetButton = document.getElementById(table.dataset.resetButton);
        const focusKey = table.dataset.searchFocusKey;
        let debounceTimer;

        if (searchInput) {
            if (focusKey && sessionStorage.getItem(focusKey) === 'true') {
                sessionStorage.removeItem(focusKey);
                searchInput.focus();
                searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
            }

            searchInput.addEventListener('input', () => {
                if (focusKey) sessionStorage.setItem(focusKey, 'true');
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => reloadWithFilters(form), 300);
            });
        }

        form.querySelectorAll('select').forEach(select => {
            select.addEventListener('change', () => reloadWithFilters(form));
        });

        if (resetButton) {
            resetButton.addEventListener('click', () => {
                if (focusKey) sessionStorage.removeItem(focusKey);
                window.location.href = window.location.pathname;
            });
        }
    }

    function initializeSorting(table) {
        const tableBody = table.querySelector('tbody');
        const headers = [...table.querySelectorAll('th[data-sort-key]')];
        let activeHeader = null;
        let direction = 1;

        headers.forEach(header => {
            header.addEventListener('click', () => {
                direction = activeHeader === header ? direction * -1 : 1;
                activeHeader = header;

                const rows = [...tableBody.querySelectorAll('tr[data-sort-row]')];
                const pinnedBottomRow = tableBody.querySelector('[data-sort-pinned-bottom]');
                rows.sort((leftRow, rightRow) => direction * compareCells(
                    leftRow.cells[header.cellIndex],
                    rightRow.cells[header.cellIndex],
                    header.dataset.sortType || 'text',
                ));
                rows.forEach(row => {
                    if (pinnedBottomRow) {
                        tableBody.insertBefore(row, pinnedBottomRow);
                    } else {
                        tableBody.appendChild(row);
                    }
                });

                headers.forEach(currentHeader => {
                    const isActive = currentHeader === header;
                    currentHeader.setAttribute('aria-sort', isActive
                        ? (direction === 1 ? 'ascending' : 'descending')
                        : 'none');
                    currentHeader.querySelector('.sort-indicator').textContent = isActive
                        ? (direction === 1 ? '↑' : '↓')
                        : '';
                });
            });

            header.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    header.click();
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-sortable-table]').forEach(table => {
            initializeFiltering(table);
            initializeSorting(table);
        });
    });
}());
