// New purchase and add-items forms: item cards, each with its own listings and sale.
// The fields are numbered (items-<i>-..., items-<i>-listings-<j>-...), see
// templates/helpers/purchase_items.html and parse_item_cards in app.py.
(() => {
    const form = document.querySelector('[data-purchase-form]');
    if (!form) return;

    const itemList = form.querySelector('[data-item-list]');
    const cardTemplate = document.getElementById('item-card-template');
    const listingTemplate = document.getElementById('listing-row-template');
    const summary = form.querySelector('[data-summary]');

    // The numbers only need to be unique, so keep counting up from the highest on the page
    const highestIndex = selector => Math.max(-1, ...Array.from(form.querySelectorAll(selector), el => Number(el.dataset.index)));
    let nextItem = highestIndex('[data-item-card]') + 1;
    let nextListing = highestIndex('[data-listing-row]') + 1;

    const cards = () => Array.from(itemList.querySelectorAll('[data-item-card]'));
    // A Single purchase hides the extra cards but keeps what's in them, in case of a switch back
    const activeCards = () => cards().filter(card => !card.hidden);
    const filledCards = () => activeCards().filter(card => card.querySelector('[data-item-name]').value.trim());
    const field = (card, name) => card.querySelector(`[name="items-${card.dataset.index}-${name}"]`);

    function fromTemplate(template, replacements) {
        let html = template.innerHTML;
        for (const [placeholder, value] of Object.entries(replacements)) {
            html = html.replaceAll(placeholder, value);
        }
        const parsed = document.createElement('template');
        parsed.innerHTML = html.trim();
        return parsed.content.firstElementChild;
    }

    function refresh() {
        const bundle = form.dataset.type === 'bundle';
        form.querySelectorAll('[data-bundle-only]').forEach(el => { el.hidden = !bundle; });
        form.querySelectorAll('[data-single-only]').forEach(el => { el.hidden = bundle; });
        const all = cards();
        all.forEach((card, position) => {
            const hide = !bundle && position > 0;
            card.hidden = hide;
            // Disabled fields aren't sent, so a hidden card is never saved
            card.querySelector('[data-card-fields]').disabled = hide;
            card.querySelector('[data-item-number]').textContent = position + 1;
            card.querySelector('[data-action="remove-item"]').disabled = all.length === 1;
        });
        updateSummary();
    }

    function updateSummary() {
        if (!summary) return;
        const count = filledCards().length;
        const parts = [count === 1 ? summary.dataset.oneItem : summary.dataset.manyItems.replace('{count}', count)];
        const costs = form.querySelectorAll('[data-cost]');
        if (costs.length) {
            const total = Array.from(costs).reduce((sum, input) => sum + (parseFloat(input.value) || 0), 0);
            parts.push(summary.dataset.currency + total.toFixed(2));
        }
        summary.textContent = parts.join(' · ');
    }

    function addCard(copyFrom) {
        const card = fromTemplate(cardTemplate, { __I__: nextItem++ });
        if (copyFrom) {
            // Duplicate: same kind of item, so keep everything but the name and notes
            for (const name of ['quantity', 'category', 'brand', 'condition', 'shelf_id']) {
                field(card, name).value = field(copyFrom, name).value;
            }
        }
        // Keep a long bundle short: fold the cards that already have a name
        cards().forEach(other => {
            if (other.querySelector('[data-item-name]').value.trim()) other.open = false;
        });
        itemList.appendChild(card);
        refresh();
        card.querySelector('[data-item-name]').focus();
    }

    function removeCard(card) {
        const name = card.querySelector('[data-item-name]').value.trim();
        const button = card.querySelector('[data-action="remove-item"]');
        if (cards().length === 1 || (name && !confirm(button.dataset.confirm))) return;
        const neighbour = card.previousElementSibling || card.nextElementSibling;
        card.remove();
        refresh();
        neighbour?.querySelector('summary').focus();
    }

    function addListing(card) {
        const row = fromTemplate(listingTemplate, { __I__: card.dataset.index, __L__: nextListing++ });
        card.querySelector('[data-listing-list]').appendChild(row);
        syncSaleListings(card);
        row.querySelector('[data-listing-platform]').focus();
    }

    function removeListing(card, row) {
        row.remove();
        syncSaleListings(card);
        card.querySelector('[data-action="add-listing"]').focus();
    }

    function setSale(card, on) {
        const sale = card.querySelector('[data-sale]');
        const addButton = card.querySelector('[data-action="add-sale"]');
        sale.hidden = !on;
        sale.disabled = !on;
        addButton.hidden = on;
        if (on) {
            syncSaleListings(card);
            syncSaleQuantity(card);
            field(card, 'sale-sale_price').focus();
        } else {
            addButton.focus();
        }
    }

    // "Sold via" offers this card's listings, by their platform
    function syncSaleListings(card) {
        const select = card.querySelector('[data-sale-listing]');
        const current = select.value;
        const rows = Array.from(card.querySelectorAll('[data-listing-row]'));
        while (select.options.length > 1) select.remove(1);
        rows.forEach(row => {
            const platform = row.querySelector('[data-listing-platform]').value.trim();
            select.add(new Option(platform || select.dataset.unnamed, row.dataset.index));
        });
        // Like the sale page, link the first listing unless the user picked something else
        const stillThere = current === '' || rows.some(row => row.dataset.index === current);
        select.value = select.hasAttribute('data-touched') && stillThere ? current : (rows[0]?.dataset.index ?? '');
    }

    function syncSaleQuantity(card) {
        card.querySelector('[data-sale-quantity]').max = card.querySelector('[data-item-quantity]').value || 1;
    }

    form.addEventListener('click', event => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const card = button.closest('[data-item-card]');
        switch (button.dataset.action) {
            case 'add-item': addCard(); break;
            case 'duplicate-item': addCard(card); break;
            case 'remove-item': removeCard(card); break;
            case 'add-listing': addListing(card); break;
            case 'remove-listing': removeListing(card, button.closest('[data-listing-row]')); break;
            case 'add-sale': setSale(card, true); break;
            case 'remove-sale': setSale(card, false); break;
        }
    });

    form.addEventListener('input', event => {
        const target = event.target;
        const card = target.closest('[data-item-card]');
        if (target.matches('[data-item-name]')) card.querySelector('[data-item-title]').textContent = target.value;
        if (target.matches('[data-item-quantity]')) syncSaleQuantity(card);
        if (target.matches('[data-listing-platform]')) syncSaleListings(card);
        updateSummary();
    });

    form.addEventListener('change', event => {
        const target = event.target;
        if (target.matches('[data-sale-listing]')) target.setAttribute('data-touched', '');
        if (target.matches('[data-type-toggle]')) {
            form.dataset.type = target.value;
            refresh();
            // A reload keeps the chosen type
            const url = new URL(location.href);
            url.searchParams.set('purchase_type', target.value);
            history.replaceState(null, '', url);
        }
    });

    // A required field inside a folded card can't be shown, so unfold the card first
    form.addEventListener('invalid', event => {
        const card = event.target.closest('details');
        if (card) card.open = true;
    }, true);

    let submitting = false;
    form.addEventListener('submit', event => {
        // A double tap on a slow connection would save the purchase twice
        if (submitting) {
            event.preventDefault();
            return;
        }
        const message = form.dataset.confirmBundle;
        const total = Number(form.dataset.existingItemCount || 0) + filledCards().length;
        if (message && total > 1 && !confirm(message)) {
            event.preventDefault();
            return;
        }
        submitting = true;
    });
    // Coming back with the Back button shows the page from memory, ready to submit again
    window.addEventListener('pageshow', () => { submitting = false; });

    // The browser may restore a different type than the server rendered
    const checkedType = form.querySelector('[data-type-toggle]:checked');
    if (checkedType) form.dataset.type = checkedType.value;
    cards().forEach(syncSaleQuantity);
    refresh();
})();
