const galleries = document.querySelectorAll<HTMLElement>('[data-gallery]');
for (const gallery of galleries) {
  const nav = gallery.querySelector<HTMLElement>('[data-gallery-nav]');
  const tabs = [...gallery.querySelectorAll<HTMLAnchorElement>('[data-gallery-tab]')];
  const panels = [...gallery.querySelectorAll<HTMLElement>('[data-gallery-panel]')];
  if (!nav || !tabs.length) continue;
  nav.setAttribute('role', 'tablist');
  nav.setAttribute('aria-orientation', 'vertical');
  nav.setAttribute('aria-label', 'CLI screenshots');
  const activate = (selected: HTMLAnchorElement, focus = false) => {
    for (const tab of tabs) {
      const active = tab === selected;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    }
    for (const panel of panels) panel.hidden = panel.id !== selected.dataset.panel;
    if (focus) selected.focus();
  };
  tabs.forEach((tab, index) => {
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', tab.dataset.panel!);
    const panel = panels.find((item) => item.id === tab.dataset.panel);
    panel?.setAttribute('role', 'tabpanel');
    panel?.setAttribute('aria-labelledby', tab.id);
    if (panel) panel.tabIndex = 0;
    tab.addEventListener('click', (event) => { event.preventDefault(); activate(tab); });
    tab.addEventListener('keydown', (event) => {
      let next = index;
      if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else if (event.key === ' ') { event.preventDefault(); activate(tab); return; }
      else return;
      event.preventDefault(); activate(tabs[next], true);
    });
  });
  const linked = tabs.find((tab) => tab.hash === window.location.hash);
  activate(linked || tabs[0]);
}

const dialog = document.querySelector<HTMLDialogElement>('#capture-dialog');
const dialogImage = dialog?.querySelector<HTMLImageElement>('img');
const dialogCaption = dialog?.querySelector<HTMLElement>('[data-dialog-caption]');
let returnFocus: HTMLElement | null = null;
if (dialog && dialogImage && dialogCaption) {
  for (const link of document.querySelectorAll<HTMLAnchorElement>('[data-capture-link]')) {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      returnFocus = link;
      dialogImage.src = link.href;
      dialogImage.alt = link.closest('figure')?.querySelector('img')?.alt || 'Actual FreeCompute CLI screenshot';
      dialogCaption.textContent = link.dataset.caption || '';
      dialog.showModal();
    });
  }
  dialog.querySelector<HTMLButtonElement>('[data-dialog-close]')?.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    dialogImage.removeAttribute('src');
    returnFocus?.focus();
  });
}

for (const button of document.querySelectorAll<HTMLButtonElement>('[data-copy]')) {
  button.hidden = false;
  button.addEventListener('click', async () => {
    const block = button.closest('[data-command]');
    const text = block?.querySelector('code')?.textContent || '';
    const status = block?.querySelector<HTMLElement>('[data-copy-status]');
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text.trim());
      if (status) status.textContent = 'Copied.';
    } catch {
      if (status) status.textContent = 'Clipboard unavailable. Select and copy the command.';
    }
  });
}
