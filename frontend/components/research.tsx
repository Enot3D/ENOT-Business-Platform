"use client";

import { ArrowLeft, ArrowRight, FileText, FolderOpen } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { date, filterLabel, market } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { AnalystOutput } from "./analyst";
import { ScoreSummary } from "./catalog";
import { ComparisonTable } from "./comparison";
import { Finance } from "./finance";
import { NicheEvidence } from "./niche";
import { ProjectCreate } from "./project-create";
import { Empty, Failure, Loading } from "./states";

export function ResearchPage({ cursor }: { cursor?: string }) {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [updatedSince, setUpdatedSince] = useState("");
  const load = useCallback((signal: AbortSignal) => api("get", "/research-projects", { query: { cursor }, signal }), [cursor]);
  const result = useResource(load);
  const projects = result.data?.items.filter((project) =>
    project.title.toLocaleLowerCase("ru").includes(title.trim().toLocaleLowerCase("ru")) &&
    (!updatedSince || project.updated_at.slice(0, 10) >= updatedSince));
  return <>
    <header className="page-heading"><div><h1>Мои исследования</h1><p>Параметры проектов и история сохранённых отчётов.</p></div></header>
    <section className="panel content-panel"><h2>Новое исследование</h2>
      <ProjectCreate filters={{ include_unknown_budget: false }} onCreate={(project) => router.push(`/research/${project.id}`)} />
    </section>
    {result.pending && <Loading />}
    {result.error ? <Failure error={result.error} retry={result.retry} /> : null}
    {result.data && <>
      {result.data.items.length > 0 && <div className="panel content-panel project-filters">
        <label>Название на странице<input type="search" value={title} onChange={(event) => setTitle(event.target.value)} /></label>
        <label>Обновлено начиная с<input type="date" value={updatedSince} onChange={(event) => setUpdatedSince(event.target.value)} /></label>
      </div>}
      {projects?.length ? <ul className="record-list">{projects.map((project) => <li key={project.id}>
        <Link className="panel record" href={`/research/${project.id}`}><span className="feature-icon"><FolderOpen size={20} /></span><span><strong>{project.title}</strong><small>{filterLabel(project.filters)}</small></span><span className="record-date">{date(project.updated_at)}</span><ArrowRight size={17} /></Link>
      </li>)}</ul> : <Empty title={result.data.items.length ? "Совпадений на странице нет" : "Исследований пока нет"} />}
      <Pagination cursor={cursor} next={result.data.next_cursor} path="/research" />
    </>}
  </>;
}

function Pagination({ cursor, next, path }: { cursor?: string; next?: string | null; path: string }) {
  if (!cursor && !next) return null;
  return <nav className="pagination" aria-label="Страницы списка">
    {cursor && <Link className="button" href={path}>Первая страница</Link>}
    {next && <Link className="button" href={`${path}?${new URLSearchParams({ cursor: next })}`}>Следующая страница <ArrowRight size={16} /></Link>}
  </nav>;
}

export function ProjectPage({ id, cursor }: { id: string; cursor?: string }) {
  const loadProject = useCallback((signal: AbortSignal) => api("get", "/research-projects/{project_id}", { path: { project_id: id }, signal }), [id]);
  const loadReports = useCallback((signal: AbortSignal) => api("get", "/research-projects/{project_id}/reports", { path: { project_id: id }, query: { cursor }, signal }), [cursor, id]);
  const project = useResource(loadProject);
  const reports = useResource(loadReports);
  return <>
    <Link href="/research" className="text-link back"><ArrowLeft size={16} /> Мои исследования</Link>
    {project.pending && <Loading />}
    {project.error ? <Failure error={project.error} retry={project.retry} /> : null}
    {project.data && <>
      <header className="page-heading"><div><p className="eyebrow">Исследование</p><h1>{project.data.title}</h1><p>{filterLabel(project.data.filters)}</p></div></header>
      <div className="release-strip"><span>Создано {date(project.data.created_at)}</span><span>Обновлено {date(project.data.updated_at)}</span></div>
      <div className="section-heading"><h2>История отчётов</h2></div>
      {reports.pending && <Loading label="Загружаем отчёты…" />}
      {reports.error ? <Failure error={reports.error} retry={reports.retry} /> : null}
      {reports.data && (reports.data.items.length
        ? <ul className="record-list">{reports.data.items.map((report) => <li key={report.id}><Link className="panel record" href={`/research/${id}/reports/${report.id}`}><span className="feature-icon"><FileText size={20} /></span><span><strong>Отчёт · версия {report.version}</strong><small>Модель {report.model_version}</small></span><span className="record-date">{date(report.created_at)}</span><ArrowRight size={17} /></Link></li>)}</ul>
        : <Empty title="У исследования пока нет отчётов"><Link className="button" href="/niches">Выбрать нишу в каталоге</Link></Empty>)}
      <Pagination cursor={cursor} next={reports.data?.next_cursor} path={`/research/${id}`} />
    </>}
  </>;
}

export function ReportPage({ projectId, reportId }: { projectId: string; reportId: string }) {
  const load = useCallback((signal: AbortSignal) => api("get", "/research-projects/{project_id}/reports/{report_id}", {
    path: { project_id: projectId, report_id: reportId }, signal,
  }), [projectId, reportId]);
  const result = useResource(load);
  const report = result.data;

  return <>
    <Link href={`/research/${projectId}`} className="text-link back"><ArrowLeft size={16} /> История исследования</Link>
    {result.pending && <Loading />}
    {result.error ? <Failure error={result.error} retry={result.retry} /> : null}
    {report && <>
      <header className="page-heading"><div><p className="eyebrow">Сохранённый снимок</p><h1>Отчёт · версия {report.version}</h1><p>{filterLabel(report.filters)}</p></div></header>
      <div className="release-strip"><span>Сохранено {date(report.created_at)}</span><span>Срез от {date(report.items[0]?.niche.updated_at)} · Модель {report.model_version}</span></div>
      <details className="panel content-panel snapshot-meta"><summary>Идентификаторы снимка</summary><dl className="key-values"><div><dt>Выпуск</dt><dd>{report.dataset_id}</dd></div><div><dt>SHA-256</dt><dd>{report.sha256}</dd></div></dl></details>
      {report.items.length > 1 && <ComparisonTable items={report.items} />}
      {report.interpretation && <section className="panel content-panel"><h2>Сохранённый вывод аналитика</h2><AnalystOutput value={report.interpretation} items={report.items} snapshot={report.sources} /></section>}
      {report.items.map((item) => <details key={item.niche.id} className="report-niche" open={report.items.length === 1}>
        <summary>{item.niche.title}</summary>
        <section className="panel content-panel"><p className="muted">{market(item.niche.market)} · {item.niche.segment}</p><ScoreSummary score={item.niche.score} /></section>
        <section className="panel content-panel"><h2>Финансовые сценарии</h2><Finance rows={item.finance} gap={item.finance_gap} /></section>
        <NicheEvidence detail={item} snapshot={report.sources} />
      </details>)}
    </>}
  </>;
}
