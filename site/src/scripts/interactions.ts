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
