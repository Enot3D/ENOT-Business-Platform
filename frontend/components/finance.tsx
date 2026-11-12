import type { Schema } from "@/lib/api";
import { budgetRange, date, kinds, missing, money, number } from "@/lib/format";

const labels: Record<Schema<"Finance">["code"], string> = {
  low: "Низкий", base: "Базовый", high: "Высокий",
  price_down_25: "Цена −25%", price_up_25: "Цена +25%",
  volume_down_25: "Объём −25%", volume_up_25: "Объём +25%",
  cost_down_50: "Себестоимость −50%", cost_up_50: "Себестоимость +50%",
};
const scenarioCodes = ["low", "base", "high"];

function FinanceTable({ rows, label }: { rows: Schema<"Finance">[]; label: string }) {
  return <div className="table-wrap" tabIndex={0} role="region" aria-label={label}><table>
    <thead><tr><th scope="col">Сценарий</th><th scope="col">Цена / ед.</th><th scope="col">Себест. / ед.</th><th scope="col">Объём / мес.</th><th scope="col">Выручка / мес.</th><th scope="col">Переменные / мес.</th><th scope="col">Постоянные / мес.</th><th scope="col">Вклад / мес.</th><th scope="col">Порог / мес.</th></tr></thead>
    <tbody>{rows.map((row) => <tr key={row.code}>
      <th scope="row">{labels[row.code]}</th><td>{money(row.price)}</td><td>{money(row.variable)}</td><td>{number.format(row.volume)}</td>
      <td>{money(row.revenue)}</td><td>{money(row.variable_total)}</td><td>{money(row.fixed)}</td>
      <td className={row.contribution < 0 ? "negative" : ""}>{money(row.contribution)}</td><td>{row.break_even == null ? "Порог не рассчитывается" : number.format(row.break_even)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function Finance({ rows, gap }: { rows: Schema<"Finance">[]; gap?: string | null }) {
  if (!rows.length) return <p className="data-gap"><strong>{missing}</strong>{gap ? ` · ${gap}` : ""}</p>;
  const ordered = Object.keys(labels).flatMap((code) => rows.filter((row) => row.code === code));
  const scenarios = ordered.filter(({ code }) => scenarioCodes.includes(code));
  const stress = ordered.filter(({ code }) => !scenarioCodes.includes(code));
  const base = rows.find(({ code }) => code === "base") ?? rows[0];
  const max = Math.max(1, ...scenarios.map(({ contribution }) => Math.abs(contribution)));
  return <>
    <div className="finance-meta">
      <span className="tag">{Array.from(new Set(rows.map(({ basis_kind }) => kinds[basis_kind]))).join(" / ")}</span>
      <span>Единица продажи · {base.unit}</span>
      <span>Старт · {budgetRange(base.start_min, base.start_max)}</span>
      <span>Модель {base.finance_version} · {date(base.calculated_at)}</span>
    </div>
    {scenarios.length > 0 && <>
      <h3>Месячный вклад по сценариям</h3>
      <div className="finance-chart">
        {scenarios.map(({ code, contribution }) => <div className="chart-row" key={code}><span>{labels[code]}</span>
          <div className="chart-track" aria-hidden="true"><span className={contribution < 0 ? "bar-loss" : ""} style={{
            left: `${contribution < 0 ? 50 + contribution / max * 50 : 50}%`,
            width: `${Math.abs(contribution) / max * 50}%`,
          }} /></div><strong>{money(contribution)}</strong></div>)}
      </div>
      <FinanceTable rows={scenarios} label="Финансовые сценарии" />
    </>}
    {stress.length > 0 && <><h3 className="spaced">Стресс-проверки базового сценария</h3><FinanceTable rows={stress} label="Стресс-проверки" /></>}
  </>;
}
