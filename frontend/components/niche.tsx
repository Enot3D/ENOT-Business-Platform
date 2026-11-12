"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { api, type Filters, type Schema } from "@/lib/api";
import { budgetRange, date, filterQuery, interval, market, missing } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { ScoreSummary } from "./catalog";
import { Claims } from "./evidence";
import { Finance } from "./finance";
import { ResearchWorkbench } from "./research-workbench";
import { Failure, Loading } from "./states";
import { CompareBar, SelectNiche } from "./workspace";

const criterionLabels = {
  D: "Спрос", U: "Неудовлетворённость", C: "Позиция среди альтернатив", P: "Экономика единицы",
  I: "Затраты на пилот", S: "Повторяемость", R: "Управляемость рисков",
};
const sections = [
  ["demand", "Спрос"], ["competition", "Конкуренция"], ["risk", "Риски"], ["economics", "Основания финансовой модели"], ["gap", "Пробелы данных"],
] as const;

export function NicheEvidence({ detail, snapshot }: { detail: Schema<"NicheDetail">; snapshot?: Schema<"SourceVersion">[] }) {
  return <>
    <section className="panel content-panel"><h2>Основания оценки</h2>
      <div className="criteria-grid">{detail.criteria.map((criterion) => <details className="criterion" key={criterion.code}>
        <summary><strong>{criterionLabels[criterion.code]}</strong><span>{criterion.rating == null ? missing : `${criterion.rating} / 5`}</span></summary>
        <p className="muted">Качество основания {criterion.quality} / 3</p>
        {criterion.gap_reason && <p className="data-gap">{criterion.gap_reason}</p>}
        {criterion.claim_ids.length > 0 && <Claims claims={detail.claims.filter(({ id }) => criterion.claim_ids.includes(id))} snapshot={snapshot} />}
      </details>)}</div>
    </section>
    {sections.map(([section, title]) => <section key={section} className="panel content-panel"><h2>{title}</h2>
      <Claims claims={detail.claims.filter((claim) => claim.section === section)} snapshot={snapshot} />
    </section>)}
  </>;
}

export function NichePage({ id, datasetId, filters }: { id: string; datasetId?: string; filters: Filters }) {
  const load = useCallback((signal: AbortSignal) => api("get", "/niches/{niche_id}", {
    path: { niche_id: id }, query: { dataset_id: datasetId }, signal,
  }), [datasetId, id]);
  const result = useResource(load);
  const detail = result.data;
  const query = filterQuery(filters);

  return <>
    <Link className="text-link back" href={query.size ? `/niches?${query}` : "/niches"}><ArrowLeft size={16} /> Каталог ниш</Link>
    {result.pending && <Loading />}
    {result.error ? <Failure error={result.error} retry={result.retry} /> : null}
    {detail && <>
      <header className="page-heading"><div><p className="eyebrow">{market(detail.niche.market)} · Ниша №{detail.niche.legacy_code}</p><h1>{detail.niche.title}</h1><p>{detail.niche.segment}</p></div><SelectNiche niche={detail.niche} /></header>
      <section className="panel content-panel detail-overview">
        <ScoreSummary score={detail.niche.score} />
        <dl className="key-values">
          <div><dt>Место в выпуске</dt><dd>{interval(detail.niche.score.rank_from, detail.niche.score.rank_to)}</dd></div>
          <div><dt>Стартовый бюджет</dt><dd>{budgetRange(detail.niche.start_min, detail.niche.start_max)}</dd></div>
          <div><dt>Обновлено</dt><dd>{date(detail.niche.updated_at)}</dd></div>
          <div><dt>Версия модели</dt><dd>{detail.niche.score.model_version}</dd></div>
        </dl>
      </section>
      <nav className="section-links" aria-label="Разделы карточки"><a href="#finance">Экономика</a><a href="#evidence">Доказательства</a><a href="#workbench">Сохранение и ИИ</a></nav>
      <section id="finance" className="panel content-panel"><h2>Финансовые сценарии</h2><Finance rows={detail.finance} gap={detail.finance_gap} /></section>
      <div id="evidence"><NicheEvidence detail={detail} /></div>
      <ResearchWorkbench key={`${detail.niche.dataset_id}:${detail.niche.id}`} items={[detail]} filters={filters} />
      <CompareBar filters={filters} />
    </>}
  </>;
}
