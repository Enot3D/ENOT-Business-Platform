import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function fitsViewport(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("pilot catalog, evidence, comparison, analysis and saved report", async ({ page }, info) => {
  const login = process.env.ENOT_E2E_LOGIN;
  const password = process.env.ENOT_E2E_PASSWORD;
  if (!login || !password) throw new Error("Set ENOT_E2E_LOGIN and ENOT_E2E_PASSWORD for a disposable account");

  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/niches");
  await expect(page).toHaveURL(/\/login\?returnTo=%2Fniches$/);
  await page.getByLabel("Логин").fill(login);
  if (info.project.name === "desktop") {
    await page.getByLabel("Пароль").fill("wrong-password");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Не удалось войти" })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Не удалось войти" })).toContainText("ID запроса");
  }
  await page.getByLabel("Пароль").fill(password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Каталог ниш" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(20);
  await fitsViewport(page);

  await page.getByLabel("Регион").fill("RU-NIZ");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page).toHaveURL(/region=RU-NIZ/);
  await expect(page.getByText("По этим фильтрам нет ниш")).toBeVisible();
  await page.getByRole("link", { name: "Показать данные по России" }).click();

  const transport = page.getByRole("article").filter({ hasText: "№03" });
  await expect(transport).toBeVisible();
  await page.getByLabel("Бюджет, ₽").fill("29999");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByText(/На странице:/)).toBeVisible();
  await expect(transport).toHaveCount(0);
  await page.getByLabel("Бюджет, ₽").fill("30000");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(transport).toContainText("Возможен при нижней оценке");
  await page.getByLabel("Бюджет, ₽").fill("150000");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(transport).toContainText("Покрывает диапазон");
  await page.getByRole("link", { name: "Сбросить", exact: true }).click();
  await expect(page.getByRole("article")).toHaveCount(20);

  await page.getByRole("article").filter({ hasText: "№06" }).getByRole("link", { name: /Открыть:/ }).click();
  await expect(page.locator("#finance")).toContainText("Нет данных");
  await page.getByRole("link", { name: "Каталог ниш", exact: true }).last().click();
  await transport.getByRole("link", { name: /Открыть:/ }).click();
  await expect(page.locator("#finance")).toBeVisible();
  await expect(page.getByText("42,22–75,56")).toBeVisible();
  await expect(page.getByText("40,74 / 100")).toBeVisible();
  await expect(page.getByText("66,67%")).toBeVisible();
  const base = page.getByRole("row", { name: /Базовый/ });
  await expect(base).toContainText(/30\s000\s₽/);
  await expect(base.getByRole("cell").last()).toHaveText("4");
  await expect(page.getByRole("region", { name: "Стресс-проверки" }).getByRole("row")).toHaveCount(7);
  await fitsViewport(page);

  const evidence = page.locator("#evidence").getByRole("button", { name: "Доказательство 1", exact: true }).filter({ visible: true }).first();
  await evidence.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Доказательство" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Дата доступа")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(evidence).toBeFocused();

  await page.getByRole("checkbox", { name: /^Сравнить:/ }).check();
  await page.getByRole("link", { name: "Каталог ниш", exact: true }).last().click();
  await page.getByRole("article").filter({ hasText: "№04" }).getByRole("checkbox").check();
  await page.getByRole("link", { name: "К сравнению" }).click();
  await expect(page.getByText(/Интервалы баллов пересекаются/)).toBeVisible();
  await expect(page.getByText(/Оплачиваемые единицы различаются/)).toBeVisible();
  await fitsViewport(page);

  await page.getByText("Новое исследование", { exact: true }).click();
  const title = `E2E ${info.project.name} ${randomUUID()}`;
  await page.getByLabel("Название исследования").fill(title);
  await page.getByRole("button", { name: "Создать исследование" }).click();
  await expect(page.getByRole("combobox", { name: "Исследование", exact: true }).locator("option:checked")).toHaveText(title);
  await page.getByRole("button", { name: "Запросить анализ" }).click();
  await expect(page.getByText("Доступна локальная сводка")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Наблюдение 1" }).first()).toBeVisible();

  if (info.project.name === "desktop") {
    const reportPath = /\/api\/v1\/research-projects\/[^/]+\/reports$/;
    const keys: string[] = [];
    await page.route(reportPath, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      keys.push(route.request().headers()["idempotency-key"]);
      if (keys.length !== 1) return route.continue();
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort();
    });
    await page.getByRole("button", { name: "Сохранить отчёт" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Сервис временно недоступен" })).toBeVisible();
    await page.getByRole("button", { name: "Сохранить отчёт" }).click();
    await expect(page.getByText("Сохранена версия 1")).toBeVisible();
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    await page.unroute(reportPath);
  } else {
    await page.getByRole("button", { name: "Сохранить отчёт" }).click();
    await expect(page.getByText("Сохранена версия 1")).toBeVisible();
  }

  await page.getByRole("link", { name: "Открыть отчёт" }).click();
  await expect(page.getByRole("heading", { name: "Отчёт · версия 1" })).toBeVisible();
  const reportUrl = page.url();
  await page.getByRole("link", { name: "История исследования" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await expect(page.getByRole("link", { name: /Отчёт · версия/ })).toHaveCount(1);
  await page.getByRole("link", { name: /Отчёт · версия/ }).click();
  await expect(page).toHaveURL(reportUrl);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Сохранённый вывод аналитика" })).toBeVisible();
  await page.getByRole("button", { name: "Наблюдение 1" }).first().click();
  await expect(page.getByRole("dialog")).toContainText("Версия источника");
  await page.getByRole("button", { name: "Закрыть" }).click();
  await fitsViewport(page);

  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page.getByRole("heading", { name: "Вход в платформу" })).toBeVisible();
  expect(await page.context().cookies(new URL("/api/v1/session", reportUrl).href)).not.toContainEqual(expect.objectContaining({ name: "enot_session" }));
  await page.goto(reportUrl);
  await expect(page.getByRole("heading", { name: "Вход в платформу" })).toBeVisible();
  expect(errors).toEqual([]);
});
