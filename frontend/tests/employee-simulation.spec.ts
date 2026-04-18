import { expect, test } from '@playwright/test'

type PositionLike = {
  ordnungszahl: string
  source_page?: number | null
  position_type?: string
}

function parsePageFromIframeSrc(src: string | null): number | null {
  if (!src) return null
  const hashIndex = src.indexOf('#')
  if (hashIndex < 0) return null
  const hash = src.slice(hashIndex + 1)
  const params = new URLSearchParams(hash.replaceAll('&', '&'))
  const pageRaw = params.get('page')
  if (!pageRaw) return null
  const parsed = Number.parseInt(pageRaw, 10)
  return Number.isFinite(parsed) ? parsed : null
}

test('employee flow: open project, jump between OZ, verify Original-LV page jump + log frontend issues', async ({ page, request }) => {
  const apiBase = process.env.E2E_API_BASE ?? 'https://tiefbaux.vercel.app/backend/api'
  const email = process.env.E2E_EMAIL ?? 'info@aicist.de'
  const password = process.env.E2E_PASSWORD ?? 'admin'

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
    if (!response.url().includes('/backend/api/')) return
    if (response.status() >= 500) {
      failedApiCalls.push(`${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })

  await page.goto('/')
  await page.getByLabel('E-Mail').fill(email)
  await page.getByLabel('Passwort').fill(password)
  await page.getByRole('button', { name: 'Anmelden' }).click()

  await expect(page.getByRole('button', { name: 'Projektarchiv' })).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Projektarchiv' }).click()

  const firstLoadButton = page.getByRole('button', { name: /Analyse laden|Projekt ansehen/ }).first()
  await expect(firstLoadButton).toBeVisible({ timeout: 20_000 })
  await firstLoadButton.click()

  // Build OZ->source_page map for the first project (same sorting as archive endpoint).
  const token = await page.evaluate(() => localStorage.getItem('tiefbaux_token'))
  expect(token).toBeTruthy()

  const projectsRes = await request.get(`${apiBase}/projects`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(projectsRes.ok()).toBeTruthy()
  const projects = (await projectsRes.json()) as Array<{ id: number }>
  expect(projects.length).toBeGreaterThan(0)
  const projectId = projects[0].id

  const detailRes = await request.get(`${apiBase}/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(detailRes.ok()).toBeTruthy()
  const detail = await detailRes.json() as { positions: PositionLike[] }
  const materialPositions = detail.positions.filter((p) => p.position_type !== 'dienstleistung' && p.source_page != null)
  expect(materialPositions.length).toBeGreaterThan(1)
  const expectedPageByOz = new Map(materialPositions.map((p) => [p.ordnungszahl, p.source_page ?? null]))

  // Ensure assignment view is active.
  const startAssignmentButton = page.getByRole('button', { name: 'Zuordnung starten' })
  if (await startAssignmentButton.isVisible().catch(() => false)) {
    await startAssignmentButton.click()
  }
  await expect(page.locator('.position-oz')).toBeVisible({ timeout: 20_000 })

  // Force material scope (avoid starting in Dienstleistung tab from persisted UI state).
  const allTab = page.getByRole('button', { name: /Alle \(/ })
  if (await allTab.isVisible().catch(() => false)) {
    await allTab.click()
  }

  for (let i = 0; i < 2; i += 1) {
    const ozText = (await page.locator('.position-oz').textContent()) ?? ''
    const oz = ozText.replace(/^OZ\s+/i, '').trim()
    const expectedPage = expectedPageByOz.get(oz) ?? null
    expect.soft(expectedPage, `OZ ${oz} has no expected source_page in API detail`).not.toBeNull()

    const originalToggle = page.getByText('Original-LV', { exact: true })
    await originalToggle.click()
    const iframe = page.locator('iframe.original-lv-iframe')
    await expect(iframe).toBeVisible()

    await expect
      .poll(async () => (await iframe.getAttribute('src')) ?? '')
      .toContain('page=', { timeout: 10_000 })

    const iframeSrc = await iframe.getAttribute('src')
    const actualPage = parsePageFromIframeSrc(iframeSrc)
    expect.soft(actualPage, `OZ ${oz}: iframe page mismatch`).toBe(expectedPage)

    // Move to next position only after confirming current one.
    const acceptAndNext = page.getByRole('button', { name: 'Übernehmen & weiter' })
    if (i === 0 && await acceptAndNext.isVisible().catch(() => false)) {
      await acceptAndNext.click()
      await expect(page.locator('.position-oz')).not.toContainText(oz)
    }
  }

  expect.soft(consoleErrors, `Console errors:\n${consoleErrors.join('\n')}`).toEqual([])
  expect.soft(pageErrors, `Page errors:\n${pageErrors.join('\n')}`).toEqual([])
  expect.soft(failedApiCalls, `Failed API calls:\n${failedApiCalls.join('\n')}`).toEqual([])
})
