// Navbar search preview (AI-generated with Claude): suggestions under the search
// field while typing, and recent searches when it is empty. The server renders the
// suggestions (templates/search_preview.html); this script fetches them and
// handles the keyboard, following the ARIA combobox pattern.
(() => {
    const DEBOUNCE_MS = 150;
    const MAX_RECENT = 5;
    const MAX_CACHED = 50;

    const t = (text) => (window.I18N && window.I18N[text]) || text;

    document.querySelectorAll("form[data-search-preview]").forEach((form, formIndex) => {
        const input = form.querySelector('input[name="q"]');
        const statusInput = form.querySelector('input[name="status"]');
        const defaultStatus = statusInput ? statusInput.value : null;
        const previewUrl = form.dataset.searchPreview;
        const recentKey = form.dataset.recentKey;

        // Panel: recent searches header (outside the listbox, since it has a button) + listbox
        const panel = document.createElement("div");
        panel.className = "search-preview";
        panel.hidden = true;

        const recentHead = document.createElement("div");
        recentHead.className = "search-preview-recent-head";
        recentHead.hidden = true;
        const recentTitle = document.createElement("span");
        recentTitle.textContent = t("Recent searches");
        const clearButton = document.createElement("button");
        clearButton.type = "button";
        clearButton.className = "btn btn-link btn-sm";
        clearButton.textContent = t("Clear");
        clearButton.setAttribute("aria-label", t("Clear recent searches"));
        recentHead.append(recentTitle, clearButton);

        const listbox = document.createElement("div");
        listbox.className = "search-preview-list";
        listbox.id = `search-preview-${formIndex}`;
        listbox.setAttribute("role", "listbox");
        listbox.setAttribute("aria-label", t("Search suggestions"));

        // Read out how many suggestions there are, since focus stays in the field
        const announcer = document.createElement("div");
        announcer.className = "visually-hidden";
        announcer.setAttribute("aria-live", "polite");

        panel.append(recentHead, listbox);
        form.append(panel, announcer);

        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-controls", listbox.id);
        input.setAttribute("aria-expanded", "false");

        const cache = new Map();
        let controller = null;
        let timer = null;
        let activeIndex = -1;
        let shownQuery = null;

        const options = () => [...listbox.querySelectorAll('[role="option"]')];

        // Keep the panel above the on-screen keyboard (visualViewport shrinks with it)
        const fitToViewport = () => {
            if (panel.hidden) return;
            const viewport = window.visualViewport;
            const visibleBottom = viewport ? viewport.offsetTop + viewport.height : window.innerHeight;
            const space = visibleBottom - panel.getBoundingClientRect().top - 12;
            panel.style.setProperty("--search-preview-space", `${Math.max(space, 160)}px`);
        };

        const setActive = (index) => {
            const list = options();
            list.forEach((option) => option.removeAttribute("aria-selected"));
            activeIndex = index;
            const option = list[index];
            if (option) {
                option.setAttribute("aria-selected", "true");
                input.setAttribute("aria-activedescendant", option.id);
                option.scrollIntoView({ block: "nearest" });
            } else {
                input.removeAttribute("aria-activedescendant");
            }
        };

        const open = () => {
            panel.hidden = false;
            input.setAttribute("aria-expanded", "true");
            fitToViewport();
        };

        const close = () => {
            panel.hidden = true;
            input.setAttribute("aria-expanded", "false");
            setActive(-1);
        };

        const showOptions = (query) => {
            options().forEach((option, i) => {
                option.id = `${listbox.id}-option-${i}`;
            });
            shownQuery = query;
            setActive(-1);
            if (listbox.children.length) open(); else close();
        };

        const loadRecent = () => {
            try {
                const saved = JSON.parse(localStorage.getItem(recentKey));
                return Array.isArray(saved) ? saved.filter((text) => typeof text === "string") : [];
            } catch {
                return [];
            }
        };

        const saveRecent = (query) => {
            if (!query) return;
            const recent = loadRecent().filter((text) => text.toLowerCase() !== query.toLowerCase());
            try {
                localStorage.setItem(recentKey, JSON.stringify([query, ...recent].slice(0, MAX_RECENT)));
            } catch {
                // Storage can be full or blocked; recent searches are only a convenience
            }
        };

        const showRecent = () => {
            const recent = loadRecent();
            const group = document.createElement("div");
            group.className = "search-preview-group";
            group.setAttribute("role", "group");
            group.setAttribute("aria-label", t("Recent searches"));
            recent.forEach((text) => {
                const option = document.createElement("button");
                option.type = "button";
                option.className = "search-preview-option";
                option.tabIndex = -1;
                option.setAttribute("role", "option");
                option.dataset.recent = text;
                option.innerHTML = '<i class="bi bi-clock-history search-preview-icon" aria-hidden="true"></i>'
                    + '<span class="search-preview-text"><span class="search-preview-title"></span></span>';
                option.querySelector(".search-preview-title").textContent = text;
                group.append(option);
            });
            listbox.replaceChildren(...(recent.length ? [group] : []));
            recentHead.hidden = !recent.length;
            announcer.textContent = "";
            showOptions(null);
        };

        const render = (html, query) => {
            listbox.innerHTML = html;
            recentHead.hidden = true;
            panel.classList.remove("is-loading");
            announcer.textContent = listbox.querySelector("[data-announce]")?.dataset.announce || "";
            showOptions(query);
        };

        const fetchPreview = async (query) => {
            controller?.abort();
            controller = new AbortController();
            try {
                const response = await fetch(`${previewUrl}?q=${encodeURIComponent(query)}`, {
                    signal: controller.signal,
                });
                // A redirect means the session ended and this is the login page
                if (!response.ok || response.redirected) throw new Error(response.statusText);
                const html = await response.text();
                if (cache.size >= MAX_CACHED) cache.delete(cache.keys().next().value);
                cache.set(query, html);
                if (input.value.trim() === query) render(html, query);
            } catch (error) {
                if (error.name !== "AbortError") panel.classList.remove("is-loading");
            }
        };

        const update = () => {
            const query = input.value.trim();
            window.clearTimeout(timer);
            if (query && query !== shownQuery && !cache.has(query)) {
                // Keep the previous suggestions while waiting; they dim if the answer is slow
                panel.classList.add("is-loading");
                timer = window.setTimeout(() => fetchPreview(query), DEBOUNCE_MS);
                return;
            }
            controller?.abort();
            panel.classList.remove("is-loading");
            if (!query) {
                showRecent();
            } else if (query === shownQuery) {
                if (listbox.children.length) open();
            } else {
                render(cache.get(query), query);
            }
        };

        input.addEventListener("input", update);
        input.addEventListener("focus", update);

        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                // Reopens the suggestions if they were closed, then steps into them
                if (panel.hidden) update();
                const count = options().length;
                if (panel.hidden || !count) return;
                event.preventDefault();
                // Moving past either end goes back to the field
                let next = activeIndex + (event.key === "ArrowDown" ? 1 : -1);
                if (next < -1) next = count - 1;
                if (next >= count) next = -1;
                setActive(next);
            } else if (event.key === "Enter" && !panel.hidden && activeIndex >= 0) {
                event.preventDefault();
                options()[activeIndex].click();
            } else if (event.key === "Escape" && !panel.hidden) {
                // A second Escape clears the field, as usual for search inputs
                event.preventDefault();
                close();
            }
        });

        // Clicking inside the panel keeps the focus (and the phone keyboard) in the field
        panel.addEventListener("mousedown", (event) => event.preventDefault());

        // Scrolling the suggestions on a phone hides the keyboard to show more of them
        listbox.addEventListener("touchmove", () => {
            if (document.activeElement === input) input.blur();
        }, { passive: true });

        listbox.addEventListener("click", (event) => {
            const option = event.target.closest('[role="option"]');
            if (!option) return;
            if (option.dataset.recent !== undefined) {
                input.value = option.dataset.recent;
                update();
                return;
            }
            // The search led somewhere, so remember it
            saveRecent(input.value.trim());
        });

        clearButton.addEventListener("click", () => {
            try {
                localStorage.removeItem(recentKey);
            } catch {
                // Nothing to clear when storage is blocked
            }
            close();
        });

        form.addEventListener("submit", () => {
            const query = input.value.trim();
            saveRecent(query);
            // When nothing matching is on sale, open all statuses instead of an empty page
            if (statusInput) {
                const results = listbox.querySelector("[data-total-count]");
                const onlyOtherStatuses = results && results.dataset.q === query
                    && results.dataset.onSaleCount === "0" && results.dataset.totalCount !== "0";
                statusInput.value = onlyOtherStatuses ? "all" : defaultStatus;
            }
        });

        document.addEventListener("pointerdown", (event) => {
            if (!form.contains(event.target)) close();
        });
        form.addEventListener("focusout", (event) => {
            if (event.relatedTarget && !form.contains(event.relatedTarget)) close();
        });
        form.closest(".collapse")?.addEventListener("hide.bs.collapse", close);
        window.addEventListener("pagehide", close);

        (window.visualViewport || window).addEventListener("resize", fitToViewport);
    });
})();
