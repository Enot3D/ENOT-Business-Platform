"use client";

import { ExternalLink, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Schema } from "@/lib/api";
import { date, kinds, market, missing, number } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { Failure, Loading } from "./states";

export type EvidenceLink = { claim: Schema<"Claim">; evidence: Schema<"Evidence"> };
const availability = { readable: "Доступен при проверке", unavailable: "Недоступен при проверке", shell: "Доступна только оболочка страницы" };
const relation = { supports: "Подтверждает", qualifies: "Уточняет", contradicts: "Противоречит" };

function safeUrl(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:") return url.href;
  } catch {}
  return undefined;
}

function Source({ source }: { source: Schema<"SourceVersion"> }) {
  const url = safeUrl(source.url);
  return <section className="source-block">
    <h3>Версия источника</h3>
    <p><strong>{source.title}</strong></p>
    <dl className="key-values">
      <div><dt>Издатель</dt><dd>{source.publisher}</dd></div>
      <div><dt>Тип</dt><dd>{source.kind}</dd></div>
      <div><dt>Ревизия</dt><dd>{source.version}</dd></div>
      <div><dt>Дата публикации</dt><dd>{date(source.published_on)}</dd></div>
      <div><dt>Дата доступа</dt><dd>{date(source.retrieved_on)}</dd></div>
      <div><dt>Доступность</dt><dd>{availability[source.availability]}</dd></div>
      <div><dt>Режим доступа</dt><dd>{source.access_mode || missing}</dd></div>
    </dl>
    {source.caveats && <p className="data-gap">{source.caveats}</p>}
    {source.license_note && <p className="muted">{source.license_note}</p>}
    {url && <a className="text-link" href={url} target="_blank" rel="noopener noreferrer">Открыть источник <ExternalLink size={15} /></a>}
  </section>;
}

function LiveSource({ id }: { id: string }) {
  const load = useCallback((signal: AbortSignal) => api("get", "/sources/{source_version_id}", { path: { source_version_id: id }, signal }), [id]);
  const resource = useResource(load);
  if (resource.pending) return <Loading label="Загружаем источник…" />;
  return resource.data ? <Source source={resource.data} /> : <Failure error={resource.error} retry={resource.retry} />;
}

function Observation({ link, snapshot }: { link: EvidenceLink; snapshot?: Schema<"SourceVersion">[] }) {
  const { observation } = link.evidence;
  const saved = snapshot?.find(({ id }) => id === observation.source_version_id);
  return <>
    <span className="tag">{kinds[link.claim.kind]}</span>
    <p>{link.claim.statement}</p>
    <h3>Наблюдение</h3>
    <dl className="key-values">
      <div><dt>Связь</dt><dd>{relation[link.evidence.relation]}</dd></div>
      <div><dt>Тип</dt><dd>{kinds[observation.kind]}</dd></div>
      <div><dt>Показатель</dt><dd>{observation.metric}</dd></div>
      {observation.value != null && <div><dt>Значение</dt><dd>{[number.format(observation.value), observation.unit, observation.currency].filter(Boolean).join(" ")}</dd></div>}
      <div><dt>География</dt><dd>{market(observation.market)}</dd></div>
      <div><dt>Период</dt><dd>{observation.period_label || (observation.period_start ? `${date(observation.period_start)} — ${date(observation.period_end)}` : missing)}</dd></div>
      <div><dt>Выборка</dt><dd>{observation.population || missing}</dd></div>
      <div><dt>Основание</dt><dd>{observation.basis || missing}</dd></div>
      <div><dt>Версия метода</dt><dd>{observation.method_version || missing}</dd></div>
      <div><dt>Расположение</dt><dd>{link.evidence.locator || observation.locator || missing}</dd></div>
    </dl>
    {observation.text_value && <p>{observation.text_value}</p>}
    {link.evidence.note && <p className="muted">{link.evidence.note}</p>}
    {observation.limitations && <p className="data-gap">{observation.limitations}</p>}
    {saved ? <Source source={saved} /> : observation.source_version_id && !snapshot
      ? <LiveSource id={observation.source_version_id} /> : <p className="muted">Версия внешнего источника отсутствует.</p>}
  </>;
}

export function EvidenceButton({ link, snapshot, label }: { link: EvidenceLink; snapshot?: Schema<"SourceVersion">[]; label: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    if (opened && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [opened]);

  function close() {
    setOpened(false);
    trigger.current?.focus();
  }

  return <>
    <button ref={trigger} type="button" className="text-link evidence-link" onClick={() => setOpened(true)}>{label}</button>
    {opened && <dialog className="source-dialog" ref={dialog} onClose={close} aria-label="Доказательство">
      <div className="dialog-heading"><h2>Доказательство</h2><button type="button" className="icon-button" aria-label="Закрыть" onClick={() => dialog.current?.close()}><X size={20} /></button></div>
      <Observation link={link} snapshot={snapshot} />
    </dialog>}
  </>;
}

export function Claims({ claims, snapshot }: { claims: Schema<"Claim">[]; snapshot?: Schema<"SourceVersion">[] }) {
  return claims.length ? <ul className="claims">{claims.map((claim) => <li key={claim.id}>
    <span className="tag">{kinds[claim.kind]}</span><p>{claim.statement}</p>
    {claim.gap_reason && <p className="data-gap">{claim.gap_reason}</p>}
    {claim.evidence.length > 0 && <div className="evidence-links">{claim.evidence.map((evidence, index) =>
      <EvidenceButton key={evidence.id} link={{ claim, evidence }} snapshot={snapshot} label={`Доказательство ${index + 1}`} />
    )}</div>}
  </li>)}</ul> : <p className="data-gap">Нет данных в этом разделе выпуска.</p>;
}
