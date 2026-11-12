"use client";

import { ArrowLeft, X } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { api, selection, type Filters, type Schema } from "@/lib/api";
import { budgetRange, date, filterQuery, interval, market, missing, money, number } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { RangeLine } from "./catalog";
import { Empty, Failure, Loading } from "./states";
import { ResearchWorkbench } from "./research-workbench";
import { useWorkspace } from "./workspace";

function base(item: Schema<"NicheDetail">) {
  return item.finance.find(({ code }) => code === "base");
}
const rows: [string, (item: Schema<"NicheDetail">) => string][] = [
  ["География", ({ niche }) => market(niche.market)],
  ["Место в выпуске", ({ niche: { score } }) => interval(score.rank_from, score.rank_to)],
  ["Уверенность", ({ niche: { score } }) => `${number.format(score.confidence)} / 100`],
  ["Покрытие", ({ niche: { score } }) => `${number.format(score.coverage)}%`],
  ["Стартовый бюджет", ({ niche }) => budgetRange(niche.start_min, niche.start_max)],
  ["Оплачиваемая единица", (item) => base(item)?.unit ?? missing],
  ["Базовый вклад / мес.", (item) => money(base(item)?.contribution)],
  ["Безубыточность, ед. / мес.", (item) => base(item)?.break_even?.toString() ?? missing],
];

export function ComparisonTable({ items }: { items: Schema<"NicheDetail">[] }) {
  return <section className="panel content-panel">
    <h2>Диапазоны Opportunity</h2>
    <div className="ranges">
      {items.map(({ niche }) => <div className="range-row" key={niche.id}><span>{niche.title}</span><RangeLine score={niche.score} /><strong>{interval(niche.score.lower, niche.score.upper)}</strong></div>)}
      <div className="range-row scale" aria-hidden="true"><span /><div><span>0</span><span>25</span><span>50</span><span>75</span><span>100</span></div><span /></div>
    </div>
    <div className="table-wrap comparison-table" tabIndex={0} role="region" aria-label="Сравнение показателей"><table>
      <thead><tr><th scope="col">Показатель</th>{items.map(({ niche }) => <th key={niche.id} scope="col">{niche.title}</th>)}</tr></thead>
      <tbody>{rows.map(([label, render]) => <tr key={label}><th scope="row">{label}</th>{items.map((item) => <td key={item.niche.id}>{render(item)}</td>)}</tr>)}</tbody>
    </table></div>
  </section>;
}

export function ComparePage({ filters }: { filters: Filters }) {
  const { picked, toggle, clear, session } = useWorkspace();
  const payload = JSON.stringify(selection(picked) ?? null);
  const csrf = session?.csrf_token;
  const load = useCallback((signal: AbortSignal) => {
    const body: Schema<"CompareRequest"> | null = JSON.parse(payload);
    return body && body.niche_ids.length >= 2 ? api("post", "/comparisons", { body, csrf, signal }) : Promise.resolve(null);
  }, [csrf, payload]);
  const comparison = useResource(load);
  const data = comparison.data;
  const query = filterQuery(filters);

  return <>
    <Link className="text-link back" href={query.size ? `/niches?${query}` : "/niches"}><ArrowLeft size={16} /> Каталог ниш</Link>
    <header className="page-heading"><div><h1>Сравнение ниш</h1><p>Интервалы на общей шкале и показатели одного выпуска.</p></div></header>
    {picked.length > 0 && <section className="panel content-panel picked-list" aria-label="Выбранные ниши">
      {picked.map((niche) => <button key={niche.id} className="button subtle" type="button" onClick={() => toggle(niche)} aria-label={`Убрать: ${niche.title}`}>{niche.title} <X size={16} /></button>)}
      <button className="text-link" type="button" onClick={clear}>Очистить выбор</button>
    </section>}
    {picked.length < 2 && <Empty title="Выберите от 2 до 5 ниш в каталоге"><Link href="/niches" className="button primary">К каталогу</Link></Empty>}
    {picked.length >= 2 && comparison.pending && <Loading label="Сравниваем ниши…" />}
    {comparison.error ? <Failure error={comparison.error} retry={comparison.retry} /> : null}
    {data && <>
      <div className="release-strip"><span>Модель {data.model_version}</span><span>Срез от {date(data.items[0]?.niche.updated_at)}</span></div>
      {data.warnings.length > 0 && <ul className="data-gap warnings">{data.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
      <ComparisonTable items={data.items} />
      <ResearchWorkbench key={payload} items={data.items} filters={filters} />
    </>}
  </>;
}
