// Text fields with a dropdown of previously used values (suggestion_input in
// templates/helpers/form_macros.html). Each value has an [X] that stops
// suggesting it, after a confirmation; records that use it keep it.
const suggestionText = text => (window.I18N && window.I18N[text]) || text;

function closeSuggestionMenus() {
    document.querySelectorAll('.suggestion-menu.show').forEach(menu => menu.classList.remove('show'));
}

function showSuggestions(input) {
    const wrapper = input.closest('.previous-value-wrapper');
    const menu = wrapper.querySelector('.suggestion-menu');
    const query = input.value.trim().toLowerCase();
    const canRemove = Boolean(document.getElementById(input.dataset.options)?.dataset.field);
    menu.innerHTML = '';

    document.querySelectorAll(`#${input.dataset.options} option`).forEach(option => {
        if (!query || option.value.toLowerCase().includes(query)) {
            const row = document.createElement('div');
            row.className = 'suggestion-row';

            const choice = document.createElement('button');
            choice.type = 'button';
            choice.className = 'dropdown-item suggestion-option';
            choice.textContent = option.value;
            choice.dataset.value = option.value;
            row.appendChild(choice);

            if (canRemove) {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'suggestion-remove';
                remove.dataset.value = option.value;
                remove.setAttribute('aria-label', suggestionText('Remove "{value}" from the list').replace('{value}', option.value));
                remove.title = suggestionText('Remove from the list');
                remove.innerHTML = '<i class="bi bi-x-lg" aria-hidden="true"></i>';
                row.appendChild(remove);
            }
            menu.appendChild(row);
        }
    });
    menu.classList.toggle('show', menu.children.length > 0);
}

async function removeSuggestion(button) {
    const input = button.closest('.previous-value-wrapper').querySelector('.previous-value-input');
    const datalist = document.getElementById(input.dataset.options);
    const value = button.dataset.value;
    const question = suggestionText('Remove "{value}" from the list? Records that use it keep it.').replace('{value}', value);
    if (!confirm(question)) return;

    try {
        const response = await fetch(datalist.dataset.hideUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ field: datalist.dataset.field, value }),
        });
        if (!response.ok) throw new Error(response.status);
    } catch {
        alert(suggestionText('The value could not be removed. Try again.'));
        return;
    }
    datalist.querySelectorAll('option').forEach(option => {
        if (option.value === value) option.remove();
    });
    showSuggestions(input);
    input.focus();
}

document.addEventListener('click', event => {
    const toggle = event.target.closest('.suggestion-toggle');
    const choice = event.target.closest('.suggestion-option');
    const remove = event.target.closest('.suggestion-remove');

    if (remove) {
        removeSuggestion(remove);
        return;
    }
    if (choice) {
        const wrapper = choice.closest('.previous-value-wrapper');
        const input = wrapper.querySelector('.previous-value-input');
        input.value = choice.dataset.value;
        // Let the page react to the new value, as if it had been typed
        input.dispatchEvent(new Event('change', { bubbles: true }));
        wrapper.querySelector('.suggestion-menu').classList.remove('show');
        return;
    }
    if (toggle) {
        const input = toggle.closest('.previous-value-wrapper').querySelector('.previous-value-input');
        showSuggestions(input);
        input.focus();
        return;
    }
    if (!event.target.closest('.previous-value-wrapper')) closeSuggestionMenus();
});

document.addEventListener('input', event => {
    if (event.target.matches('.previous-value-input')) showSuggestions(event.target);
});
