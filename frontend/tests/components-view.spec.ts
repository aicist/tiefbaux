import { expect, test } from '@playwright/test'

const EMAIL = 'info@aicist.de'
const PASSWORD = 'admin'

const TARGET_PROJECT_HINT = 'Brohl'

test('assignment view renders new spec sections (Gütewerte, Druckfestigkeit, Komponenten)', async ({ page }) => {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const failedApiCalls: string[] = []

  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text())
  })
  page.on('pageerror', (err) => {
    pageErrors.push(err.message)
  })
  page.on('response', (response) => {
    if (!response.url().includes('/api/')) return
    if (response.status() >= 400) {
      failedApiCalls.push(`${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })

  await page.goto('/')
  await page.getByLabel('E-Mail').fill(EMAIL)
  await page.getByLabel('Passwort').fill(PASSWORD)
  await page.getByRole('button', { name: 'Anmelden' }).click()

  await expect(page.getByRole('button', { name: 'Projektarchiv' })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Projektarchiv' }).click()

  const projectRow = page.locator('text=' + TARGET_PROJECT_HINT).first()
  await expect(projectRow).toBeVisible({ timeout: 20_000 })
  const loadButton = projectRow
    .locator('xpath=ancestor::*[descendant::button][1]')
    .getByRole('button', { name: /Analyse laden|Projekt ansehen/ })
    .first()
  await loadButton.click()

  const positionOz = page.locator('.position-oz')
  const startAssignmentButton = page.getByRole('button', { name: /Zuordnung starten/i })
  const continueButton = page.getByRole('button', { name: /Nochmal durchgehen/i })

  await expect(positionOz.or(startAssignmentButton).or(continueButton)).toBeVisible({ timeout: 20_000 })
  if (await startAssignmentButton.isVisible().catch(() => false)) {
    await startAssignmentButton.click()
  } else if (!(await positionOz.isVisible().catch(() => false))) {
    await continueButton.click()
  }
  await expect(positionOz).toBeVisible({ timeout: 20_000 })

  // Walk through all 6 positions by rejecting each one (Esc opens confirm,
  // then we click "Ablehnen" to finalise and advance). This guarantees we see
  // every position including OZ 4.5.7 with its multi-component rendering.
  const seen = new Map<string, { hasComponents: boolean; hasGutewerte: boolean; hasDruckfestigkeit: boolean }>()

  const recordCurrent = async () => {
    const ozText = (await positionOz.textContent().catch(() => '')) ?? ''
    const oz = ozText.replace(/^OZ\s+/i, '').trim()
    if (!oz || seen.has(oz)) return oz
    const hasComponents = await page
      .locator('.position-section', { hasText: 'Komponenten dieser Position' })
      .first()
      .isVisible()
      .catch(() => false)
    const hasGutewerte = await page
      .locator('.position-section', { hasText: 'Gütewerte & Prüfanforderungen' })
      .first()
      .isVisible()
      .catch(() => false)
    const hasDruckfestigkeit = await page
      .locator('.position-spec-row', { hasText: 'Druckfestigkeit' })
      .first()
      .isVisible()
      .catch(() => false)
    seen.set(oz, { hasComponents, hasGutewerte, hasDruckfestigkeit })
    await page.screenshot({
      path: `test-results/oz-${oz.replace(/\./g, '_')}-fullpage.png`,
      fullPage: true,
    })
    return oz
  }

  // Ensure "Alle" filter is active so we walk all 6 positions.
  const alleTab = page.locator('.tab-btn').filter({ hasText: /^Alle\s*\(/ }).first()
  if (await alleTab.isVisible().catch(() => false)) {
    await alleTab.click()
    await page.waitForTimeout(300)
  }

  for (let i = 0; i < 8; i += 1) {
    const prev = await recordCurrent()
    const hits = [...seen.values()]
    const allThreeCovered =
      hits.some(v => v.hasComponents) &&
      hits.some(v => v.hasGutewerte) &&
      hits.some(v => v.hasDruckfestigkeit)
    if (allThreeCovered && seen.size >= 3) break
    // Reject and confirm to advance.
    const rejectBtn = page.getByRole('button', { name: 'Ablehnen', exact: true })
    if (!(await rejectBtn.isVisible().catch(() => false))) break
    await rejectBtn.click()
    // Confirmation dialog.
    const confirmBtn = page.getByRole('button', { name: /Ja, ohne Zuordnung|Ja, ablehnen|Bestätigen/i })
    await confirmBtn.waitFor({ state: 'visible', timeout: 3000 })
    await confirmBtn.click()
    await page.waitForTimeout(400)
    const current = await positionOz.textContent().catch(() => '') ?? ''
    const oz = current.replace(/^OZ\s+/i, '').trim()
    if (!oz || oz === prev) break
  }

  // eslint-disable-next-line no-console
  console.log('Seen positions:', [...seen.entries()])

  const withComponents = [...seen.entries()].filter(([, v]) => v.hasComponents)
  const withGutewerte = [...seen.entries()].filter(([, v]) => v.hasGutewerte)
  const withDruckfestigkeit = [...seen.entries()].filter(([, v]) => v.hasDruckfestigkeit)

  expect(withGutewerte.length, 'No position rendered Gütewerte & Prüfanforderungen').toBeGreaterThan(0)
  expect(withDruckfestigkeit.length, 'No position rendered Druckfestigkeit row').toBeGreaterThan(0)
  expect(withComponents.length, 'No position rendered Komponenten dieser Position').toBeGreaterThan(0)

  expect.soft(consoleErrors, `Console errors:\n${consoleErrors.join('\n')}`).toEqual([])
  expect.soft(pageErrors, `Page errors:\n${pageErrors.join('\n')}`).toEqual([])
  expect.soft(failedApiCalls, `Failed API calls:\n${failedApiCalls.join('\n')}`).toEqual([])
})
