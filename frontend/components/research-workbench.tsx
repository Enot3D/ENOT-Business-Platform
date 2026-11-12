"use client";

import { ArrowUpRight, Bookmark, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { api, selection, type Filters, type Schema } from "@/lib/api";
import { filterLabel } from "@/lib/format";
import { useWriteKey } from "@/lib/idempotency";
import { useResource } from "@/lib/resource";
import { AnalystStatus, processing } from "./analyst";
import { ProjectCreate } from "./project-create";
import { Failure, Loading } from "./states";
import { useWorkspace } from "./workspace";

export function ResearchWorkbench({ items, filters }: { items: Schema<"NicheDetail">[]; filters: Filters }) {
  const { session } = useWorkspace();
  const selected = selection(items.map(({ niche }) => niche));
  const write = useWriteKey();
  const [projects, setProjects] = useState<Schema<"Project">[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState<"report" | "ai">();
  const [error, setError] = useState<unknown>();
  const [interpretation, setInterpretation] = useState<Schema<"Interpretation">>();
  const [includeAi, setIncludeAi] = useState(true);
  const [report, setReport] = useState<Schema<"Report">>();

  const load = useCallback((signal: AbortSignal) => api("get", "/research-projects", { query: { cursor }, signal }), [cursor]);
  const page = useResource(load);
  const visibleProjects = [...new Map([...projects, ...(page.data?.items ?? [])].map((project) => [project.id, project])).values()];

  function choose(id: string) {
    setProjectId(id);
    setInterpretation(undefined);
    setReport(undefined);
    setError(undefined);
    setIncludeAi(true);
  }

  async function run() {
    if (!selected || !session || !projectId || busy) return;
    setError(undefined);
    setBusy("ai");
    try {
      const scope = `ai:${projectId}`;
      const value = await api("post", "/research-projects/{project_id}/interpretations", {
        path: { project_id: projectId }, csrf: session.csrf_token, key: write.key(scope, selected), body: selected,
      });
      write.complete(scope, selected);
      setInterpretation(value);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }

  async function save() {
    if (!selected || !session || !projectId || busy) return;
    const body = {
      ...selected, filters,
      interpretation_id: includeAi && interpretation && !processing(interpretation.status) ? interpretation.id : null,
    };
    const scope = `report:${projectId}`;
    setError(undefined);
    setBusy("report");
    try {
      const value = await api("post", "/research-projects/{project_id}/reports", {
        path: { project_id: projectId }, csrf: session.csrf_token, key: write.key(scope, body), body,
      });
      write.complete(scope, body);
      setReport(value);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(undefined);
    }
  }

  if (!selected) return <section id="workbench" className="panel content-panel"><h2>Сохранение и ИИ</h2><p className="data-gap">Для этой версии модели действия пока недоступны.</p></section>;

  return <section id="workbench" className="panel content-panel workbench">
    <h2>Сохранение и ИИ-аналитик</h2>
    <p className="muted">Выберите исследование для анализа или сохранения снимка выбранных ниш.</p>
    <fieldset disabled={!!busy} className="project-choice">
      <label>Исследование<select value={projectId} onChange={(event) => choose(event.target.value)}>
        <option value="">Выберите исследование</option>
        {visibleProjects.map((project) => <option key={project.id} value={project.id}>{project.title}</option>)}
      </select></label>
      {page.data?.next_cursor && <button type="button" className="button" onClick={() => {
        setProjects(visibleProjects);
        setCursor(page.data?.next_cursor ?? undefined);
      }}>Загрузить ещё</button>}
      <details><summary>Новое исследование</summary><ProjectCreate filters={filters} onCreate={(project) => {
        setProjects((current) => [project, ...current]);
        choose(project.id);
      }} /></details>
    </fieldset>
    {page.pending && <Loading label="Загружаем исследования…" />}
    {page.error ? <Failure error={page.error} retry={page.retry} /> : null}
    <p className="muted">Параметры снимка · {filterLabel(filters)}</p>
    <div className="workbench-actions">
      <button type="button" className="button" onClick={run} disabled={!projectId || !!busy || !!interpretation && processing(interpretation.status)}>
        <Sparkles size={17} />{busy === "ai" ? "Отправляем…" : interpretation ? "Запросить повторно" : "Запросить анализ"}
      </button>
      <button type="button" className="button primary" onClick={save} disabled={!projectId || !!busy}>
        <Bookmark size={17} />{busy === "report" ? "Сохраняем…" : report ? "Сохранить новую версию" : "Сохранить отчёт"}
      </button>
    </div>
    {error ? <Failure error={error} /> : null}
    {report && <div className="saved" role="status"><strong>Сохранена версия {report.version}</strong><Link className="text-link" href={`/research/${report.project_id}/reports/${report.id}`}>Открыть отчёт <ArrowUpRight size={16} /></Link></div>}
    {interpretation && <>
      <AnalystStatus key={interpretation.id} value={interpretation} items={items} onUpdate={setInterpretation} />
      {!processing(interpretation.status) && <label className="check"><input type="checkbox" checked={includeAi} onChange={(event) => setIncludeAi(event.target.checked)} /> Включить вывод аналитика в отчёт</label>}
    </>}
  </section>;
}
