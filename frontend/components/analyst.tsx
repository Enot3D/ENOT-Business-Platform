"use client";

import { useEffect, useState } from "react";
import { api, type Schema } from "@/lib/api";
import { kinds } from "@/lib/format";
import { EvidenceButton, type EvidenceLink } from "./evidence";
import { Failure } from "./states";

export const processing = (status: Schema<"Interpretation">["status"]) => status === "queued" || status === "running";

const statuses: Record<Schema<"Interpretation">["status"], string> = {
  queued: "В очереди",
  running: "Анализ выполняется",
  succeeded: "Анализ готов",
  insufficient_data: "Недостаточно данных",
  fallback: "Доступна локальная сводка",
  failed: "Анализ завершился ошибкой",
};

export function AnalystOutput({ value, items, snapshot }: {
  value: Schema<"Interpretation">; items: Schema<"NicheDetail">[]; snapshot?: Schema<"SourceVersion">[];
}) {
  const evidence = new Map<string, EvidenceLink>();
  for (const item of items) {
    for (const claim of item.claims) {
      for (const link of claim.evidence) evidence.set(link.observation.id, { claim, evidence: link });
    }
  }

  return <div className="analyst-output">
    <strong className="status-tag" role="status">{statuses[value.status]}</strong>
    <p className="muted">{[value.provider, value.model, `Промпт ${value.prompt_version}`].filter(Boolean).join(" · ")}</p>
    {value.error_code && <p className="data-gap">Код ответа {value.error_code}</p>}
    {value.items.length > 0 && <ul className="claims">{value.items.map((statement, index) => <li key={index}>
      <span className="tag">{kinds[statement.kind]}</span><p>{statement.statement}</p>
      <div className="evidence-links">{statement.observation_ids.map((id, position) => {
        const link = evidence.get(id);
        return link ? <EvidenceButton key={id} link={link} snapshot={snapshot} label={`Наблюдение ${position + 1}`} /> : <span key={id} className="muted">Наблюдение {position + 1} отсутствует в карточках</span>;
      })}</div>
    </li>)}</ul>}
    {value.gaps.length > 0 && <><h3>Пробелы в данных</h3><ul>{value.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul></>}
  </div>;
}

export function AnalystStatus({ value, items, onUpdate }: {
  value: Schema<"Interpretation">; items: Schema<"NicheDetail">[]; onUpdate: (value: Schema<"Interpretation">) => void;
}) {
  const [error, setError] = useState<unknown>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!processing(value.status) || error) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await api("get", "/research-projects/{project_id}/interpretations/{interpretation_id}", {
          path: { project_id: value.project_id, interpretation_id: value.id }, signal: controller.signal,
        });
        if (!controller.signal.aborted) onUpdate(response);
      } catch (error) {
        if (!controller.signal.aborted) setError(error);
      }
    }, 2500);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [attempt, error, onUpdate, value]);

  return <>
    <AnalystOutput value={value} items={items} />
    {error ? <Failure error={error} retry={() => { setError(undefined); setAttempt((n) => n + 1); }} /> : null}
  </>;
}
