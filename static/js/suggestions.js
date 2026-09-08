function closeSuggestionMenus() {
    document.querySelectorAll('.suggestion-menu.show').forEach(menu => menu.classList.remove('show'));
}

function showSuggestions(input) {
    const wrapper = input.closest('.previous-value-wrapper');
    const menu = wrapper.querySelector('.suggestion-menu');
    const query = input.value.trim().toLowerCase();
    menu.innerHTML = '';

    document.querySelectorAll(`#${input.dataset.options} option`).forEach(option => {
        if (!query || option.value.toLowerCase().includes(query)) {
            const choice = document.createElement('button');
            choice.type = 'button';
            choice.className = 'dropdown-item suggestion-option';
            choice.textContent = option.value;
            choice.dataset.value = option.value;
            menu.appendChild(choice);
        }
    });
    menu.classList.toggle('show', menu.children.length > 0);
}

document.addEventListener('click', event => {
    const toggle = event.target.closest('.suggestion-toggle');
    const choice = event.target.closest('.suggestion-option');

    if (choice) {
        const wrapper = choice.closest('.previous-value-wrapper');
        wrapper.querySelector('.previous-value-input').value = choice.dataset.value;
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
