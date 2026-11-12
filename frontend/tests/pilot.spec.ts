import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

async function fitsViewport(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("pilot catalog, evidence, comparison, analysis and saved report", async ({ page }, info) => {
  const phone = info.project.name === "phone";
  const login = phone ? `qa-${randomUUID()}@enot.example.com` : process.env.ENOT_E2E_LOGIN;
  const password = phone ? `QA1-${randomUUID()}` : process.env.ENOT_E2E_PASSWORD;
  if (!login || !password) throw new Error("Set ENOT_E2E_LOGIN and ENOT_E2E_PASSWORD for a disposable account");
  const loginField = page.getByLabel("Электронная почта или логин");
  const passwordField = page.getByLabel("Пароль", { exact: true });
  const enter = page.getByRole("button", { name: "Войти", exact: true });

  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const malformed = "/login?returnTo=%2F%2F%5Bbad";
  const catalogUrl = "/niches?country=RU";
  const desktop = info.project.name === "desktop";
  const response = await page.goto(malformed);
  expect(response?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Вход в платформу" })).toBeVisible();

  if (!desktop) {
    await page.goto(catalogUrl);
    await expect(page).toHaveURL(`/login?returnTo=${encodeURIComponent(catalogUrl)}`);
  }
  if (phone) {
    await page.getByRole("link", { name: "Зарегистрироваться" }).click();
    await expect(page).toHaveURL("/register");
    await page.getByLabel("Имя пользователя").fill("Мобильный QA");
    await page.getByLabel("Электронная почта").fill(login);
    await passwordField.fill(password);
    await page.getByLabel("Подтверждение пароля").fill("Different12345");
    await page.getByRole("button", { name: "Зарегистрироваться" }).click();
    await expect(page.getByRole("alert")).toContainText("Пароли не совпадают.");
    await fitsViewport(page);
    await page.getByLabel("Подтверждение пароля").fill(password);
    await page.getByRole("button", { name: "Зарегистрироваться" }).click();
    await expect(page).toHaveURL("/");
    await page.reload();
    await expect(page.getByRole("link", { name: "Личный кабинет" })).toBeVisible();
    await page.getByRole("link", { name: "Личный кабинет" }).click();
    await expect(page.getByText(login, { exact: true })).toBeVisible();
    await page.getByLabel("Имя пользователя").fill("Мобильный QA 2");
    await page.getByRole("button", { name: "Сохранить имя" }).click();
    await expect(page.getByText("Имя сохранено.")).toBeVisible();
    await expect(page.getByLabel("Имя пользователя")).toHaveValue("Мобильный QA 2");
    await fitsViewport(page);
    await page.goto(catalogUrl);
  } else {
    await loginField.fill(login);
    if (desktop) {
      await passwordField.fill("wrong-password");
      await enter.click();
      await expect(page.getByRole("alert").filter({ hasText: "Не удалось войти" })).toBeVisible();
      await expect(page.getByRole("alert").filter({ hasText: "Не удалось войти" })).toContainText("ID запроса");
    }
    await passwordField.fill(password);
    await enter.click();
    await expect(page).toHaveURL(desktop ? "/" : catalogUrl);
  }

  if (desktop) {
    for (const returnTo of ["https://example.com/niches", "//example.com/niches", "//enot.invalid/niches", "/login", "/niches/..//example.com"]) {
      await page.goto(`/login?${new URLSearchParams({ returnTo })}`);
      await expect(page).toHaveURL("/");
    }
    await page.goto(`/login?returnTo=${encodeURIComponent(catalogUrl)}`);
    await expect(page).toHaveURL(catalogUrl);
  }

  await expect(page.getByRole("heading", { name: "Каталог ниш" })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(20);
  await fitsViewport(page);

  if (phone) {
    const firstTitle = await page.getByRole("article").first().getByRole("heading").innerText();
    const search = page.getByRole("searchbox", { name: "Поиск по каталогу" });
    await search.fill(firstTitle);
    await page.getByRole("button", { name: "Найти" }).click();
    await expect(page.getByRole("article")).toHaveCount(1);
    await search.clear();
    await page.getByRole("button", { name: "Найти" }).click();
    await expect(page.getByRole("article")).toHaveCount(20);
  }
  const filterToggle = page.getByText("Фильтры каталога", { exact: true });
  const region = page.getByLabel("Регион");
  const budget = page.getByLabel("Бюджет, ₽");
  if (phone) {
    await expect(region).toBeHidden();
    await filterToggle.click();
  }
  await expect(region).toBeVisible();
  await expect(page.getByLabel("Страна")).toHaveValue("RU");

  await region.fill("RU-NIZ");
  await filterToggle.click();
  await expect(region).toBeHidden();
  await filterToggle.click();
  await expect(region).toHaveValue("RU-NIZ");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page).toHaveURL(/region=RU-NIZ/);
  await expect(page.getByText("По этим фильтрам нет ниш")).toBeVisible();
  await page.getByRole("link", { name: "Показать данные по России" }).click();

  const transport = page.getByRole("article").filter({ hasText: "№03" });
  await expect(transport).toBeVisible();
  await budget.fill("29999");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByText(/На странице:/)).toBeVisible();
  await expect(transport).toHaveCount(0);
  await budget.fill("30000");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(transport).toContainText("Возможен при нижней оценке");
  await budget.fill("150000");
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(transport).toContainText("Покрывает диапазон");
  await filterToggle.click();
  await expect(budget).toBeHidden();
  await filterToggle.click();
  await expect(budget).toHaveValue("150000");
  await page.reload();
  await expect(transport).toContainText("Покрывает диапазон");
  if (phone) {
    await expect(budget).toBeHidden();
    await filterToggle.click();
  }
  await expect(budget).toHaveValue("150000");
  await page.getByRole("button", { name: "Сбросить", exact: true }).click();
  await expect(page).toHaveURL("/niches");
  await expect(budget).toHaveValue("");
  await expect(page.getByLabel("Страна")).toHaveValue("");
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

  if (phone) {
    await page.getByText("Свой финансовый сценарий", { exact: true }).click();
    await page.getByLabel("Цена за единицу, ₽").fill("5000");
    await page.getByLabel("Себестоимость единицы, ₽").fill("1000");
    await page.getByLabel("Постоянные расходы в месяц, ₽").fill("10000");
    await page.getByLabel("Продажи в месяц, ед.").fill("4");
    await page.getByRole("button", { name: "Рассчитать сценарий" }).click();
    await expect(page.locator(".finance-calculator")).toContainText(/6\s000\s₽/);
    await expect(page.locator(".finance-calculator")).toContainText("3 ед. в месяц");
  }

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
  const statusPath = /\/api\/v1\/research-projects\/[^/]+\/interpretations\/[^/]+$/;
  if (info.project.name === "desktop") {
    await page.route(statusPath, (route) => route.abort("timedout"), { times: 1 });
  }
  await page.getByRole("button", { name: "Запросить анализ" }).click();
  if (info.project.name === "desktop") {
    const timeout = page.getByRole("alert").filter({ hasText: "Сервис временно недоступен" });
    await expect(timeout).toBeVisible();
    await expect(page.getByText(/Интервалы баллов пересекаются/)).toBeVisible();
    await timeout.getByRole("button", { name: "Повторить" }).click();
  }
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
  if (phone) {
    await loginField.fill(login);
    await passwordField.fill(password);
    await page.getByRole("button", { name: "Показать пароль" }).click();
    await expect(passwordField).toHaveAttribute("type", "text");
    await page.getByRole("button", { name: "Скрыть пароль" }).click();
    await enter.click();
    await expect(page).toHaveURL(reportUrl);
    await expect(page.getByRole("heading", { name: "Сохранённый вывод аналитика" })).toBeVisible();
  }
  expect(errors).toEqual([]);
});
