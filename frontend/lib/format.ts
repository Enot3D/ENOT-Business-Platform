import type { Filters, Schema } from "./api";

export const missing = "Нет данных";
export const number = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const rub = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
export const money = (value: number | null | undefined) => value == null ? missing : rub.format(value);
export const date = (value?: string | null) => value
  ? new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value))
  : missing;
export const interval = (low: number, high: number) => `${number.format(low)}–${number.format(high)}`;
export const budgetRange = (low?: number | null, high?: number | null) =>
  low == null || high == null ? missing : `${number.format(low)}–${money(high)}`;

export function market(value: Schema<"Market">) {
  return value.region ? `${value.name} · ${value.country} / ${value.region}` : value.name;
}

export const kinds = { fact: "Факт", calculation: "Расчёт", estimate: "Оценка", hypothesis: "Гипотеза" } as const;

export function readFilters(params: Pick<URLSearchParams, "get">): Filters {
  const country = params.get("country") || undefined;
  const region = params.get("region") || undefined;
  const industry = params.get("industry") || undefined;
  const budget = params.get("budget_rub");
  const budgetValue = budget && /^\d+$/.test(budget) ? Number(budget) : NaN;
  return {
    ...(country && /^[A-Z]{2}$/.test(country) ? { country, ...(region ? { region: region.slice(0, 32) } : {}) } : {}),
    ...(industry ? { industry: industry.slice(0, 64) } : {}),
    ...(Number.isSafeInteger(budgetValue) && budgetValue <= 1e12 ? { budget_rub: budgetValue } : {}),
    include_unknown_budget: params.get("include_unknown_budget") === "true",
  };
}

export function filterLabel(filters: Filters) {
  return [
    filters.country === "RU" ? "Россия" : filters.country,
    filters.region,
    filters.industry,
    filters.budget_rub == null ? null : `Бюджет до ${money(filters.budget_rub)}`,
    filters.include_unknown_budget ? "Включая неизвестный бюджет" : null,
  ].filter(Boolean).join(" · ") || "Все ниши выпуска";
}

export function filterQuery(filters: Filters) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== false && value != null) query.set(key, String(value));
  }
  return query;
}
