// Tabs only control visibility; submitting either form remains ordinary, accessible HTML.
const tabs = document.querySelectorAll('[data-tab]');
const panels = document.querySelectorAll('[data-panel]');

// Switching state in one place keeps the selected tab and visible form in sync.
function activateTab(tabName) {
  tabs.forEach((tab) => {
    const isActive = tab.dataset.tab === tabName;
    tab.classList.toggle('is-active', isActive);
    tab.setAttribute('aria-selected', String(isActive));
  });

  panels.forEach((panel) => panel.classList.toggle('is-hidden', panel.dataset.panel !== tabName));
}

// A click changes the panel without a page reload; server validation still works normally.
tabs.forEach((tab) => tab.addEventListener('click', () => activateTab(tab.dataset.tab)));
