import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('FreeCompute product landing page', () => {
  test('provides a visible keyboard skip link that focuses the main content', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused();
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeInViewport();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('main')).toBeFocused();
  });

  test('renders actual product proof without console errors or missing images', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/');
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Your workspace.More compute.');
    await expect(page.getByRole('link', { name: 'Set up FreeCompute' })).toHaveAttribute('href', '#setup');
    await expect(page.getByRole('tab', { name: /Write code/ })).toHaveAttribute('aria-selected', 'true');
    const hero = page.getByRole('img', { name: 'Actual FreeCompute CLI returning Java prime-number code through the configured Kaggle Qwen worker.' });
    await expect(hero).toBeVisible();
    await expect.poll(() => hero.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    expect(errors).toEqual([]);
  });

  test('selects screenshots with the keyboard and restores focus after enlargement', async ({ page }) => {
    await page.goto('/');
    const first = page.getByRole('tab', { name: /Write code/ });
    await first.focus();
    await page.keyboard.press('ArrowDown');
    const inspection = page.getByRole('tab', { name: /Inspect & test/ });
    await expect(inspection).toBeFocused();
    await expect(inspection).toHaveAttribute('aria-selected', 'true');
    const panel = page.getByRole('tabpanel', { name: /Inspect & test/ });
    await expect(panel).toContainText('Permission is pending');
    const enlarge = panel.getByRole('link', { name: 'Enlarge file inspection & proposed test screenshot' });
    await enlarge.click();
    const dialog = page.getByRole('dialog', { name: 'Actual CLI screenshot' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Close screenshot' })).toBeFocused();
    await expect.poll(() => dialog.getByRole('img').evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(enlarge).toBeFocused();
  });

  test('switches to web-tool and honest telemetry captures', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('tab', { name: /Search the web/ }).click();
    await expect(page.getByRole('tabpanel', { name: /Search the web/ })).toContainText('not independently fact-checked');
    await page.getByRole('tab', { name: /Check your worker/ }).click();
    const panel = page.getByRole('tabpanel', { name: /Check your worker/ });
    await expect(panel).toContainText('explicitly unknown');
    await expect(panel.getByRole('img')).toBeVisible();
  });

  test('copies the launch command without including a key', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await page.goto('/');
    await page.getByRole('button', { name: 'Copy connect your text worker' }).click();
    await expect(page.getByText('Copied.', { exact: true })).toBeVisible();
    const command = await page.evaluate(() => navigator.clipboard.readText());
    expect(command).toBe('freecompute --remote-url "PASTE-KAGGLE-URL-HERE"');
    expect(command).not.toContain('API_KEY');
  });

  test('reports clipboard refusal with a usable manual fallback', async ({ page }) => {
    await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: async () => { throw new DOMException('Denied', 'NotAllowedError'); } },
    }));
    await page.goto('/');
    await page.getByRole('button', { name: 'Copy connect your text worker' }).click();
    await expect(page.getByText('Clipboard unavailable. Select and copy the command.')).toBeVisible();
    await expect(page.getByRole('region', { name: 'Connect your text worker' })).toContainText('freecompute --remote-url');
  });

  test('keeps the page within narrow, tablet and desktop viewports', async ({ page }) => {
    for (const width of [320, 390, 768, 1024, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/');
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  });

  test('honors reduced motion and has no automated WCAG A/AA violations', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/');
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior)).toBe('auto');
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).options({ rules: { 'label-content-name-mismatch': { enabled: true } } }).analyze();
    expect(results.violations).toEqual([]);
    await page.getByRole('tab', { name: /Check your worker/ }).click();
    await page.getByRole('tabpanel', { name: /Check your worker/ }).getByRole('link', { name: 'Enlarge worker status screenshot' }).click();
    const modalResults = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
    expect(modalResults.violations).toEqual([]);
  });

  test('remains readable and navigable without JavaScript', async ({ browser, baseURL }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto(baseURL!);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'CLI screenshots' }).getByRole('link', { name: /Inspect & test/ })).toBeVisible();
    await page.getByRole('navigation', { name: 'CLI screenshots' }).getByRole('link', { name: /Inspect & test/ }).click();
    await expect(page.getByText('Permission is pending', { exact: false })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Copy connect your text worker' })).not.toBeVisible();
    await context.close();
  });

  test('loads its setup guide and real source/notebook downloads', async ({ page, request }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Open the setup guide' }).click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('From notebookto your terminal.');
    await expect(page.getByRole('region', { name: 'Windows PowerShell installation' })).toContainText('python -m pip install -e .');
    await expect(page.getByRole('region', { name: 'Reconnect inside FreeCompute' })).toContainText('/connect PASTE-KAGGLE-URL-HERE');
    const source = await request.get('/downloads/freecompute-v1-source.zip');
    expect(source.ok()).toBe(true);
    expect((await source.body()).subarray(0, 2).toString()).toBe('PK');
    const notebook = await request.get('/downloads/freecompute_dual_gpu_server.ipynb');
    expect(notebook.ok()).toBe(true);
    expect((await notebook.json()).nbformat).toBe(4);
    const checksums = await request.get('/downloads/SHA256SUMS.txt');
    expect(await checksums.text()).toContain('freecompute-v1-source.zip');
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
    expect(results.violations).toEqual([]);
  });
});
