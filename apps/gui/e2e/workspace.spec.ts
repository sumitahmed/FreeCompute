import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

function info() { return JSON.parse(readFileSync(process.env.FC_GUI_E2E_INFO!, 'utf8')) as { url: string; token: string; workspace: string } }
async function connect(page: Page) {
  await page.goto('/')
  await page.getByLabel('Local API token').fill(info().token)
  await page.getByRole('button', { name: 'Connect to Core' }).click()
  await expect(page.getByText('SIMULATED INFERENCE', { exact: true })).toBeVisible()
  await expect(page.getByText('Core connected', { exact: true })).toBeVisible()
}
async function newTask(page: Page, prompt: string) {
  await page.getByRole('button', { name: /New session/ }).click()
  await expect(page.getByLabel('Task prompt')).toBeEnabled()
  await page.getByLabel('Task prompt').fill(prompt)
  await page.getByRole('button', { name: 'Send task' }).click()
}

test('approved coding flow streams, executes real tools, and survives refresh', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await connect(page)
  await newTask(page, '[demo:edit] Inspect calculator.py, fix fractional division, and run the local tests.')
  await expect(page.getByText('ASSISTANT · STREAMING', { exact: true }).first()).toBeVisible()
  const edit = page.getByRole('region', { name: 'Approval for edit_file' })
  await expect(edit).toBeVisible()
  await expect(edit.getByLabel('Change preview')).toContainText('return a // b')
  await page.screenshot({ path: 'test-results/freecompute-approval.png', fullPage: true })
  await edit.getByRole('button', { name: 'Approve change' }).click()
  const command = page.getByRole('region', { name: 'Approval for run_command' })
  await expect(command).toBeVisible()
  await expect(command).toContainText('-m unittest -v test_calculator')
  await command.getByRole('button', { name: 'Approve command' }).click()
  await expect(page.locator('.final-answer')).toContainText('real local unittest command exited 0')
  await expect(page.locator('.command-output')).toContainText('Ran 2 tests')
  expect(readFileSync(join(info().workspace, 'calculator.py'), 'utf8')).toContain('return a / b')
  await page.reload()
  await expect(page.locator('.final-answer')).toContainText('real local unittest command exited 0')
  await expect(page.getByRole('navigation', { name: 'Sessions' }).getByRole('button')).toHaveCount(1)
  await page.screenshot({ path: 'test-results/freecompute-workspace.png', fullPage: true })
  expect(errors).toEqual([])
})

test('a closed client does not grant approval; reconnect can explicitly deny', async ({ page, context }) => {
  await connect(page)
  await newTask(page, '[demo:write] Propose a disposable local note for review.')
  await expect(page.getByRole('region', { name: 'Approval for write_file' })).toBeVisible()
  await page.close()
  const reconnected = await context.newPage()
  await reconnected.goto('/')
  const card = reconnected.getByRole('region', { name: 'Approval for write_file' })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Deny' }).click()
  await expect(reconnected.locator('.final-answer')).toBeVisible()
  await expect(reconnected.getByRole('region', { name: 'Tool write_file' }).getByText('denied', { exact: true })).toBeVisible()
})

test('worker queue and browser network reconnect retain the same task', async ({ page, context }) => {
  await connect(page)
  await page.getByRole('button', { name: 'Simulate worker disconnect' }).click()
  await newTask(page, 'A queued fixture task after reconnect.')
  await expect(page.locator('.task-meta')).toContainText('queued')
  await expect(page.locator('.queue-row').first()).toBeVisible()
  await context.setOffline(true)
  await expect(page.getByText(/The client is disconnected/)).toBeVisible({ timeout: 10000 })
  await context.setOffline(false)
  await expect(page.getByText('Core connected', { exact: true })).toBeVisible({ timeout: 10000 })
  await page.getByRole('button', { name: 'Reconnect simulated worker' }).click()
  await expect(page.locator('.final-answer')).toContainText('No model or GPU was contacted')
  await expect(page.locator('.queue-row')).toHaveCount(0)
})

test('cancellation shows local confirmation and quarantined capacity until explicit reconciliation', async ({ page }) => {
  await connect(page)
  await newTask(page, '[demo:long] Stream a long fixture response for cancellation.')
  await expect(page.getByText('ASSISTANT · STREAMING', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Cancel task' }).click()
  await expect(page.getByText('Stopped locally', { exact: true })).toBeVisible()
  await expect(page.getByText(/Remote cancellation: unconfirmed/)).toBeVisible()
  const reconcile = page.getByRole('button', { name: 'Reconcile idle lease' })
  await expect(reconcile).toBeDisabled()
  await page.getByLabel('I independently confirmed this worker is idle.').check()
  await reconcile.click()
  await expect(reconcile).toHaveCount(0)
  await expect(page.locator('.queue-row')).toHaveCount(0)
})

test('registry compatibility, engine failures, and narrow responsive layout are usable', async ({ page }) => {
  await connect(page)
  const incompatible = page.getByLabel('Worker', { exact: true }).locator('option[value="demo-chat-worker"]')
  await expect(incompatible).toBeDisabled()
  await page.getByLabel('Profile', { exact: true }).selectOption('demo-chat')
  await expect(incompatible).toBeEnabled()
  await page.getByLabel('Profile', { exact: true }).selectOption('demo-code')
  await newTask(page, '[demo:failure] Simulate an engine authentication failure.')
  await expect(page.locator('.task-meta')).toContainText('failed')
  await expect(page.getByText(/SIMULATED engine authentication failure/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Toggle light or dark appearance' }).click()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByLabel('Task prompt')).toBeVisible()
  await page.screenshot({ path: 'test-results/freecompute-mobile-light.png', fullPage: true })
})
