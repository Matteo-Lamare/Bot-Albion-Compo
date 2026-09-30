import { test, expect } from '@playwright/test';

test('API protégée inaccessible sans authentification', async ({ request }) => {
  const response = await request.get('/api/auth/me');

  expect(response.status()).toBe(401);
});
