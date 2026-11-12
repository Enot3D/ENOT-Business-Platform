"use client";

import { useState, type FormEvent } from "react";
import { api, type Schema } from "@/lib/api";
import { money, number } from "@/lib/format";
import { Failure } from "./states";
import { useWorkspace } from "./workspace";

const fields = {
  price: "Цена за единицу, ₽",
  variable: "Себестоимость единицы, ₽",
  fixed: "Постоянные расходы в месяц, ₽",
  volume: "Продажи в месяц, ед.",
} satisfies Record<keyof Schema<"FinanceInputs">, string>;

export function FinanceCalculator({ base }: { base?: Schema<"Finance"> }) {
  const { session } = useWorkspace();
  const [result, setResult] = useState<Schema<"FinanceCalculation">>();
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);

  async function calculate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || pending) return;
    const data = new FormData(event.currentTarget);
    setPending(true);
    setError(undefined);
    setResult(undefined);
    try {
      setResult(await api("post", "/finance/calculate", {
        csrf: session.csrf_token,
        body: {
          price: Number(data.get("price")),
          variable: Number(data.get("variable")),
          fixed: Number(data.get("fixed")),
          volume: Number(data.get("volume")),
        },
      }));
    } catch (error) {
      setError(error);
    } finally {
      setPending(false);
    }
  }

  return <details className="finance-calculator">
    <summary>Свой финансовый сценарий</summary>
    <form className="form-stack" onSubmit={calculate}>
      <p className="muted">Задайте свои допущения. Расчёт доступен до закрытия страницы.</p>
      <div className="filter-fields">
        {(Object.keys(fields) as Array<keyof typeof fields>).map(key =>
          <label key={key}>{fields[key]}<input name={key} type="number" inputMode="numeric"
            min={0} max={10_000_000} step={1} required defaultValue={base?.[key]} /></label>,
        )}
      </div>
      <button className="button primary" disabled={pending}>{pending ? "Считаем…" : "Рассчитать сценарий"}</button>
    </form>
    {error ? <Failure error={error} /> : null}
    {result && <dl className="key-values" aria-live="polite">
      <div><dt>Выручка в месяц</dt><dd>{money(result.revenue)}</dd></div>
      <div><dt>Переменные расходы в месяц</dt><dd>{money(result.variable_total)}</dd></div>
      <div><dt>Вклад в месяц</dt><dd>{money(result.contribution)}</dd></div>
      <div><dt>Порог безубыточности</dt><dd>{result.break_even === null ? "Порог не рассчитывается" : `${number.format(result.break_even)} ед. в месяц`}</dd></div>
    </dl>}
  </details>;
}
