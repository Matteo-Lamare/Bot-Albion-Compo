import { test, expect } from '@playwright/test';

test('Un utilisateur peut se connecter', async ({ page }) => {
  await page.goto('/');

  await page.getByLabel('Pseudo').fill(
    process.env.E2E_ADMIN_PSEUDO || 'admin'
  );

  await page.getByLabel('Mot de passe').fill(
    process.env.E2E_ADMIN_PASSWORD || 'admin123'
  );

  const loginResponsePromise = page.waitForResponse(
    response =>
      response.url().includes('/api/auth/login') &&
      response.request().method() === 'POST'
  );

  await page.getByRole('button', { name: 'Se connecter' }).click();

  const loginResponse = await loginResponsePromise;

  expect(loginResponse.status()).toBe(200);
  await expect(page).toHaveURL(/\/bibliotheque/);
});