import { expect, test } from '@playwright/test'

test('login screen loads', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'TiefbauX' })).toBeVisible()
  await expect(page.getByLabel('E-Mail')).toBeVisible()
  await expect(page.getByLabel('Passwort')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Anmelden' })).toBeVisible()
})
