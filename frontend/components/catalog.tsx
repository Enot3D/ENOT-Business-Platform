"use client";

import { ArrowRight, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, type FormEvent } from "react";
import { api, type Filters, type Niche, type Schema } from "@/lib/api";
import { budgetRange, date, filterQuery, interval, market, number, readFilters } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { Empty, Failure, Loading } from "./states";
import { CompareBar, SelectNiche } from "./workspace";

const industries: Record<string, string> = {
  b2b: "Услуги для бизнеса", document_management: "Документооборот",
  ecommerce: "Электронная коммерция", hospitality: "Гостеприимство",
  industry: "Промышленность", manufacturing: "Производство", payments: "Платежи", transport: "Транспорт",
};
const industryLabel = (code: string) => industries[code] ?? code;
const loadDataset = (signal: AbortSignal) => api("get", "/datasets/current", { signal });

export function RangeLine({ score }: { score: Schema<"Score"> }) {
  return <div className="range-track" aria-hidden="true"><span style={{ left: `${score.lower}%`, width: `${score.upper - score.lower}%` }} /></div>;
}

export function ScoreSummary({ score }: { score: Schema<"Score"> }) {
  return <div className="score">
    <div className="score-top"><span>Opportunity</span><strong>{interval(score.lower, score.upper)} <small>/ 100</small></strong></div>
    <RangeLine score={score} />
    <dl className="metrics">
      <div><dt>Уверенность</dt><dd>{number.format(score.confidence)} / 100</dd></div>
      <div><dt>Покрытие</dt><dd>{number.format(score.coverage)}%</dd></div>
    </dl>
  </div>;
}

function BudgetFit({ niche, budget }: { niche: Niche; budget?: number }) {
  if (budget == null) return null;
  const label = niche.start_min == null ? "Бюджет неизвестен"
    : niche.start_max == null ? "Верхняя граница неизвестна"
    : budget < niche.start_max ? "Возможен при нижней оценке" : "Покрывает диапазон";
  return <span className="budget-fit">{label}</span>;
}

function CatalogCard({ niche, filters }: { niche: Niche; filters: Filters }) {
  const query = filterQuery(filters);
  query.set("dataset_id", niche.dataset_id);
  return <article className="panel niche-card" aria-label={niche.title}>
    <div className="card-meta"><span className="tag">{industryLabel(niche.industry)}</span><span>№{niche.legacy_code}</span></div>
    <h2><Link href={`/niches/${niche.id}?${query}`}>{niche.title}</Link></h2>
    <p className="muted card-market">{market(niche.market)} · {date(niche.updated_at)}</p>
    <ScoreSummary score={niche.score} />
    <div className="card-budget"><span>Стартовый бюджет</span><strong>{budgetRange(niche.start_min, niche.start_max)}</strong><BudgetFit niche={niche} budget={filters.budget_rub} /></div>
    <div className="card-actions"><SelectNiche niche={niche} /><Link href={`/niches/${niche.id}?${query}`} className="text-link" aria-label={`Открыть: ${niche.title}`}>Подробнее <ArrowRight size={16} /></Link></div>
  </article>;
}

function CatalogFilters({ filters, dataset, apply }: { filters: Filters; dataset?: Schema<"Dataset">; apply: (filters: Filters) => void }) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const params = new URLSearchParams();
    for (const name of ["country", "region", "industry", "budget_rub", "include_unknown_budget"]) {
      const value = String(form.get(name) ?? "").trim();
      if (value) params.set(name, name === "country" ? value.toUpperCase() : value);
    }
    if (params.has("region") && !params.has("country")) params.set("country", "RU");
    apply(readFilters(params));
  }

  return <details className="panel filters" open>
    <summary><SlidersHorizontal size={18} /> Фильтры каталога</summary>
    <form onSubmit={submit}>
      <div className="filter-fields">
        <label>Страна <input list="catalog-countries" name="country" defaultValue={filters.country} placeholder="Код, например RU" maxLength={2} pattern="[A-Za-z]{2}" /></label>
        <datalist id="catalog-countries">{Array.from(new Set(dataset?.markets.map(({ country }) => country))).map((country) => <option key={country} value={country}>{country === "RU" ? "Россия" : country}</option>)}</datalist>
        <label>Регион <input list="catalog-regions" name="region" defaultValue={filters.region} placeholder="Код региона" maxLength={32} /></label>
        <datalist id="catalog-regions">{dataset?.markets.filter(({ region }) => region).map((value) => <option key={`${value.country}-${value.region}`} value={value.region ?? ""}>{value.name}</option>)}</datalist>
        <label>Отрасль <select name="industry" defaultValue={filters.industry ?? ""}>
          <option value="">Все отрасли</option>
          {Array.from(new Set([...(dataset?.industries ?? []), ...(filters.industry ? [filters.industry] : [])])).map((value) => <option key={value} value={value}>{industryLabel(value)}</option>)}
        </select></label>
        <label>Бюджет, ₽ <input name="budget_rub" type="number" inputMode="numeric" min={0} max={1e12} step={1} placeholder="Без ограничения" defaultValue={filters.budget_rub} /></label>
      </div>
      <div className="filter-actions"><label className="check"><input type="checkbox" name="include_unknown_budget" value="true" defaultChecked={filters.include_unknown_budget} /> Включать ниши с неизвестным бюджетом</label>
        <Link href="/niches" className="button subtle">Сбросить</Link><button className="button primary">Применить</button></div>
    </form>
  </details>;
}

export function Catalog() {
  const params = useSearchParams();
  const router = useRouter();
  const serialized = filterQuery(readFilters(params)).toString();
  const filters = readFilters(new URLSearchParams(serialized));
  const cursor = params.get("cursor") || undefined;
  const pinned = params.get("dataset_id") || undefined;
  const dataset = useResource(loadDataset);
  const loadNiches = useCallback((signal: AbortSignal) => api("get", "/niches", {
    query: { ...readFilters(new URLSearchParams(serialized)), dataset_id: pinned, cursor, limit: 20 }, signal,
  }), [cursor, pinned, serialized]);
  const results = useResource(loadNiches);

  function apply(next: Filters) {
    const query = filterQuery(next);
    router.push(query.size ? `/niches?${query}` : "/niches");
  }

  const page = results.data;
  const more = new URLSearchParams(serialized);
  if (page?.next_cursor) {
    more.set("dataset_id", page.dataset_id);
    more.set("cursor", page.next_cursor);
  }

  return <>
    <header className="page-heading"><div><p className="eyebrow">Рынок и возможности</p><h1>Каталог ниш</h1><p>Сопоставляйте оценки, бюджет и качество данных перед проверкой гипотезы.</p></div></header>
    <div className="release-strip">
      <span>{dataset.data && (!page || dataset.data.id === page.dataset_id) ? `Выпуск ${dataset.data.version}` : page ? `Выпуск ${page.dataset_id}` : "Опубликованный выпуск"}</span>
      <span>{page ? `Обновлено ${date(page.updated_at)} · Модель ${page.model_version}` : dataset.data ? `Опубликован ${date(dataset.data.published_at)}` : "География выпуска загружается вместе с данными"}</span>
    </div>
    {dataset.error ? <Failure error={dataset.error} retry={dataset.retry} /> : null}
    <CatalogFilters key={serialized} filters={filters} dataset={dataset.data} apply={apply} />
    <div className="section-heading"><h2>Ниши</h2><span aria-live="polite">{page ? `На странице: ${page.items.length}${page.next_cursor ? " · есть ещё" : ""}` : null}</span></div>
    {results.pending && <Loading />}
    {results.error ? <Failure error={results.error} retry={results.retry} /> : null}
    {page && (page.items.length
      ? <div className="niche-grid">{page.items.map((niche) => <CatalogCard key={niche.id} niche={niche} filters={filters} />)}</div>
      : <Empty title="По этим фильтрам нет ниш"><Link className="button" href="/niches?country=RU">Показать данные по России</Link><Link className="text-link" href="/niches">Сбросить фильтры</Link></Empty>)}
    {(cursor || page?.next_cursor) && <nav className="pagination" aria-label="Страницы каталога">{cursor && <Link className="button" href={serialized ? `/niches?${serialized}` : "/niches"}>Первая страница</Link>}{page?.next_cursor && <Link className="button" href={`/niches?${more}`}>Следующая страница <ArrowRight size={16} /></Link>}</nav>}
    <CompareBar filters={filters} />
  </>;
}
