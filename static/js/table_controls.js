// DISCLAIMER: This script was AI generated.
// I chose AI for this because it would require a significant amount of time for a mainly quality-of-life feature.
// This project's goal is to learn database logic, Python, and how to build a working app.
// This script was made to unify and centralize multiple JS snippets I had used for building tables in .html files and make it more customizable and dynamic.

/*
 * Shared controls for the app's data tables.
 *
 * A table can opt into filtering and header sorting with
 * `data-sortable-table`. To also get draggable, configurable columns, add
 * `data-column-preferences-key` to the table and `data-column-id` to every
 * header. A `data-column-locked` header stays visible and at the end.
 */
(function () {
    'use strict';

    const COLUMN_STORAGE_PREFIX = 'resale-desk.table-columns.v1.';

    // -------------------------------------------------------------
    // FILTERING
    // -------------------------------------------------------------

    function buildQueryString(form) {
        const params = new URLSearchParams();
        for (const [key, value] of new FormData(form).entries()) {
            if (value) params.set(key, value);
        }
        return params.toString();
    }

    function reloadWithFilters(form) {
        const queryString = buildQueryString(form);
        window.location.href = queryString
            ? `${window.location.pathname}?${queryString}`
            : window.location.pathname;
    }

    function initializeFiltering(table) {
        const form = document.getElementById(table.dataset.filterForm);
        if (!form) return;

        const searchInput = form.querySelector('input[name="q"]');
        const resetButton = document.getElementById(table.dataset.resetButton);

        if (searchInput) {
            let debounceTimer;
            const focusKey = table.dataset.searchFocusKey;

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

    function compareCells(cellA, cellB, type, direction) {
        const valueA = cellA.dataset.sortValue || '';
        const valueB = cellB.dataset.sortValue || '';
        const numberA = Number(valueA);
        const numberB = Number(valueB);
        const validA = type === 'number'
            ? valueA.trim() !== '' && Number.isFinite(numberA)
            : valueA !== '';
        const validB = type === 'number'
            ? valueB.trim() !== '' && Number.isFinite(numberB)
            : valueB !== '';

        // Missing and invalid numeric values always stay at the bottom.
        if (!validA && validB) return 1;
        if (validA && !validB) return -1;
        if (!validA && !validB) return 0;

        if (type === 'number') return direction * (numberA - numberB);

        return direction * valueA.localeCompare(valueB, undefined, {
            sensitivity: 'base',
            numeric: type === 'date',
        });
    }

    function initializeSorting(table) {
        const tableBody = table.querySelector('tbody');
        const headers = [...table.querySelectorAll('th[data-sort-key]')];
        let activeHeader = null;
        let direction = 1;

        function sortBy(header) {
            if (header.dataset.skipNextSort === 'true') {
                delete header.dataset.skipNextSort;
                return;
            }

            direction = activeHeader === header ? direction * -1 : 1;
            activeHeader = header;
            const rows = [...tableBody.querySelectorAll('tr[data-sort-row]')];
            const pinnedBottomRow = tableBody.querySelector('[data-sort-pinned-bottom]');

            rows.sort((rowA, rowB) => compareCells(
                rowA.cells[header.cellIndex],
                rowB.cells[header.cellIndex],
                header.dataset.sortType || 'text',
                direction,
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
                currentHeader.setAttribute(
                    'aria-sort',
                    isActive ? (direction === 1 ? 'ascending' : 'descending') : 'none',
                );
                const indicator = currentHeader.querySelector('.sort-indicator');
                if (indicator) indicator.textContent = isActive ? (direction === 1 ? '↑' : '↓') : '';
            });
        }

        headers.forEach(header => {
            header.addEventListener('click', () => sortBy(header));
            header.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    sortBy(header);
                }
            });
        });
    }

    // -------------------------------------------------------------
    // COLUMN WORKSPACE
    // -------------------------------------------------------------

    function storageKey(table) {
        return `${COLUMN_STORAGE_PREFIX}${table.dataset.columnPreferencesKey}`;
    }

    function readColumnPreferences(table) {
        try {
            const stored = localStorage.getItem(storageKey(table));
            return stored ? JSON.parse(stored) : null;
        } catch (error) {
            return null;
        }
    }

    function saveColumnPreferences(table, state) {
        try {
            localStorage.setItem(storageKey(table), JSON.stringify(state));
        } catch (error) {
            // The table still works when browser storage is unavailable.
        }
    }

    function columnLabel(header) {
        const copy = header.cloneNode(true);
        copy.querySelectorAll('.sort-indicator').forEach(indicator => indicator.remove());
        return copy.textContent.trim() || 'Actions';
    }

    function normaliseColumnState(columns, savedState) {
        const defaultOrder = columns.map(column => column.id);
        const movableColumns = columns.filter(column => !column.locked);
        const lockedColumns = columns.filter(column => column.locked);
        const savedOrder = Array.isArray(savedState?.order) ? savedState.order : [];
        const savedHidden = Array.isArray(savedState?.hidden) ? savedState.hidden : [];
        const movableIds = movableColumns.map(column => column.id);
        const savedMovableIds = savedOrder.filter(
            (id, index) => movableIds.includes(id) && savedOrder.indexOf(id) === index,
        );
        const orderedMovableIds = [
            ...savedMovableIds,
            ...movableIds.filter(id => !savedMovableIds.includes(id)),
        ];

        return {
            order: [
                ...orderedMovableIds,
                ...lockedColumns.map(column => column.id),
            ],
            hidden: savedHidden.filter(id => movableIds.includes(id)),
            defaultOrder,
        };
    }

    function updateColspanRows(table, visibleColumnCount) {
        table.querySelectorAll('tbody tr').forEach(row => {
            if (row.cells.length === 1 && row.cells[0].hasAttribute('colspan')) {
                row.cells[0].colSpan = visibleColumnCount;
            }
        });
    }

    function applyColumnState(table, columns, state) {
        const headerRow = table.tHead?.rows[0];
        const tableBody = table.tBodies[0];
        if (!headerRow || !tableBody) return;

        const columnsById = new Map(columns.map(column => [column.id, column]));
        const currentHeaderIds = [...headerRow.cells].map(header => header.dataset.columnId);
        const hiddenIds = new Set(state.hidden);

        state.order.forEach(id => headerRow.append(columnsById.get(id).header));

        [...tableBody.rows].forEach(row => {
            if (row.cells.length !== currentHeaderIds.length) return;
            const cellsById = new Map(
                [...row.cells].map((cell, index) => [currentHeaderIds[index], cell]),
            );
            state.order.forEach(id => row.append(cellsById.get(id)));
        });

        state.order.forEach((id, index) => {
            const column = columnsById.get(id);
            const hidden = hiddenIds.has(id) && !column.locked;
            column.header.hidden = hidden;

            [...tableBody.rows].forEach(row => {
                if (row.cells.length === state.order.length) {
                    row.cells[index].hidden = hidden;
                }
            });
        });

        updateColspanRows(table, state.order.filter(id => !hiddenIds.has(id)).length);
    }

    function createColumnPicker(table, columns, state, onChange) {
        const details = document.createElement('details');
        details.className = 'table-column-picker table-column-picker-inline';
        const summary = document.createElement('summary');
        summary.className = 'btn btn-outline-secondary btn-sm';
        summary.textContent = 'Columns';
        details.append(summary);

        const menu = document.createElement('div');
        menu.className = 'table-column-picker-menu shadow-sm';
        const title = document.createElement('div');
        title.className = 'small fw-semibold mb-2';
        title.textContent = 'Toggle columns';
        menu.append(title);

        const checkboxes = new Map();
        columns.filter(column => !column.locked).forEach(column => {
            const label = document.createElement('label');
            label.className = 'form-check table-column-option';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input';
            checkbox.checked = !state.hidden.includes(column.id);
            checkbox.addEventListener('change', () => {
                state.hidden = checkbox.checked
                    ? state.hidden.filter(id => id !== column.id)
                    : [...state.hidden, column.id];
                onChange();
            });
            const labelText = document.createElement('span');
            labelText.className = 'form-check-label';
            labelText.textContent = column.label;
            label.append(checkbox, labelText);
            menu.append(label);
            checkboxes.set(column.id, checkbox);
        });

        const resetButton = document.createElement('button');
        resetButton.type = 'button';
        resetButton.className = 'btn btn-link btn-sm px-0 mt-2';
        resetButton.textContent = 'Reset columns';
        resetButton.addEventListener('click', () => {
            state.order = [...state.defaultOrder];
            state.hidden = [];
            onChange();
        });
        menu.append(resetButton);
        details.append(menu);
        const actionsHeader = table.querySelector('thead th[data-column-id="actions"]');
        if (actionsHeader) {
            actionsHeader.classList.add('table-actions-header');
            actionsHeader.append(details);
        }

        return {
            refresh() {
                columns.filter(column => !column.locked).forEach(column => {
                    checkboxes.get(column.id).checked = !state.hidden.includes(column.id);
                });
            },
        };
    }

    function initializeColumnWorkspace(table) {
        if (!table.dataset.columnPreferencesKey) return;

        const headerRow = table.tHead?.rows[0];
        if (!headerRow) return;
        const columns = [...headerRow.cells].map(header => ({
            id: header.dataset.columnId,
            header,
            label: columnLabel(header),
            locked: header.hasAttribute('data-column-locked'),
        }));

        if (columns.some(column => !column.id)) return;

        const state = normaliseColumnState(columns, readColumnPreferences(table));
        let picker;
        const saveAndApply = () => {
            state.hidden = [...new Set(state.hidden)];
            applyColumnState(table, columns, state);
            saveColumnPreferences(table, {
                order: state.order,
                hidden: state.hidden,
            });
            picker.refresh();
        };

        picker = createColumnPicker(table, columns, state, saveAndApply);
        saveAndApply();

        let draggedId = null;
        columns.filter(column => !column.locked).forEach(column => {
            const { header, id } = column;
            header.draggable = true;
            header.classList.add('column-draggable');
            header.title = 'Click to sort. Drag to reorder.';

            header.addEventListener('dragstart', event => {
                draggedId = id;
                header.classList.add('column-dragging');
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', id);
            });

            header.addEventListener('dragover', event => {
                if (!draggedId || draggedId === id) return;
                event.preventDefault();

                const midpoint = header.getBoundingClientRect().left + header.offsetWidth / 2;
                const placeAfterTarget = event.clientX > midpoint;
                header.classList.toggle('column-drop-before', !placeAfterTarget);
                header.classList.toggle('column-drop-after', placeAfterTarget);
                event.dataTransfer.dropEffect = 'move';
            });

            header.addEventListener('dragleave', () => {
                header.classList.remove('column-drop-before', 'column-drop-after');
            });

            header.addEventListener('drop', event => {
                if (!draggedId || draggedId === id) return;
                event.preventDefault();
                header.classList.remove('column-drop-before', 'column-drop-after');

                const order = state.order.filter(columnId => columnId !== draggedId);
                const targetIndex = order.indexOf(id);
                const midpoint = header.getBoundingClientRect().left + header.offsetWidth / 2;
                const placeAfterTarget = event.clientX > midpoint;
                order.splice(targetIndex + (placeAfterTarget ? 1 : 0), 0, draggedId);
                state.order = order;
                header.dataset.skipNextSort = 'true';
                window.setTimeout(() => {
                    delete header.dataset.skipNextSort;
                }, 0);
                saveAndApply();
            });

            header.addEventListener('dragend', () => {
                draggedId = null;
                columns.forEach(({ header: currentHeader }) => {
                    currentHeader.classList.remove('column-dragging', 'column-drop-before', 'column-drop-after');
                });
            });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-sortable-table]').forEach(table => {
            initializeFiltering(table);
            initializeColumnWorkspace(table);
            initializeSorting(table);
        });
    });
}());
