import { test, expect } from '@playwright/test';

test('Un utilisateur peut créer une compo et la retrouver dans la bibliothèque', async ({ page }) => {
  const nomCompo = `Compo E2E ${Date.now()}`;

  // Connexion
  await page.goto('/');

  await page.getByRole('textbox', { name: 'Pseudo' }).fill(
    process.env.E2E_ADMIN_PSEUDO || 'admin'
  );

  await page.getByRole('textbox', { name: 'Mot de passe' }).fill(
    process.env.E2E_ADMIN_PASSWORD || 'admin123'
  );

  await page.getByRole('button', { name: 'Se connecter' }).click();

  await expect(page).toHaveURL(/\/bibliotheque/);

  // Nouvelle composition
  await page.getByRole('link', { name: 'Nouvelle compo' }).click();

  await page.getByRole('textbox', { name: 'Nom de la compo *' }).fill(nomCompo);

  await page
    .getByLabel('Type de contenu *')
    .selectOption('Terre ancestrale');

  await page
    .getByRole('spinbutton', { name: 'Taille de groupe *' })
    .fill('8');

  await page
    .getByRole('textbox', { name: 'Notes (optionnel)' })
    .fill('Créée automatiquement par Playwright');

  await page
    .getByRole('textbox', { name: 'Ex. Tank principal — laissez' })
    .fill('B1');

  // Arme
  await page.getByRole('button', { name: 'Choisir un objet…' }).first().click();
  await page.getByRole('listitem').filter({ hasText: 'Arc de siège' }).click();

  await page.getByRole('button', { name: 'Carreau explosif' }).click();
  await page.getByText('Tir automatique').click();

  await page.getByRole('button', { name: 'Brise-tir' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Salve Explosive' }).click();

  await page.getByRole('button', { name: 'Bien préparé' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Fureur' }).click();

  // Casque
  await page.getByRole('button', { name: 'Choisir un objet…' }).first().click();
  await page.getByRole('listitem').filter({ hasText: "Capuche d'assassin" }).click();

  await page.getByRole('button', { name: 'Méditation' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Purification' }).click();

  await page.getByRole('button', { name: 'Esprit équilibré' }).click();
  await page.getByText('Promptitude').click();

  // Torse
  await page.getByRole('button', { name: 'Choisir un objet…' }).first().click();
  await page.getByRole('listitem').filter({ hasText: 'Armure de chevalier' }).click();

  await page.getByRole('button', { name: 'Bourrasque' }).click();
  await page.getByText("Chaîne d'âme").click();

  await page.getByRole('button', { name: '—' }).first().click();
  await page.getByRole('listitem').filter({ hasText: 'Brise-esprit' }).click();

  // Bottes
  await page.getByRole('button', { name: 'Choisir un objet…' }).first().click();
  await page.getByRole('listitem').filter({ hasText: 'Chaussures de ténacité' }).click();

  await page.getByRole('button', { name: 'Angle mort' }).click();

  await page.getByRole('button', { name: 'Esprit équilibré' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Promptitude' }).click();

  // Cape
  await page.getByRole('button', { name: 'Choisir un objet…' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Cape de Brecilien' }).click();

  // Enregistrement
  await page.getByRole('button', { name: 'Enregistrer' }).click();

  // Une création réussie redirige vers /compo?id=...
  await expect(page).toHaveURL(/\/compo\?id=\d+/);

  // Retour à la bibliothèque
  await page.getByRole('link', { name: 'Bibliothèque', exact: true }).click();

  await expect(page).toHaveURL(/\/bibliotheque/);

  // Vérification que la compo créée apparaît
  await expect(
    page.getByRole('link', { name: nomCompo, exact: true })
  ).toBeVisible();
});