"use client";

import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, type Filters, type Schema } from "@/lib/api";
import { useWriteKey } from "@/lib/idempotency";
import { Failure } from "./states";
import { useWorkspace } from "./workspace";

export function ProjectCreate({ filters, onCreate }: { filters: Filters; onCreate: (project: Schema<"Project">) => void }) {
  const { session } = useWorkspace();
  const write = useWriteKey();
  const [title, setTitle] = useState("");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || busy || !title.trim()) return;
    const body = { title: title.trim(), filters };
    setBusy(true);
    setError(undefined);
    try {
      const project = await api("post", "/research-projects", { csrf: session.csrf_token, key: write.key("project", body), body });
      write.complete("project", body);
      setTitle("");
      onCreate(project);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }

  return <form onSubmit={submit} className="project-create">
    <label>Название исследования<input required maxLength={120} placeholder="Например, проверка спроса в логистике" value={title} onChange={(event) => setTitle(event.target.value)} disabled={busy} /></label>
    <button className="button" disabled={busy || !title.trim()}><Plus size={17} />{busy ? "Создаём…" : "Создать исследование"}</button>
    {error ? <Failure error={error} /> : null}
  </form>;
}
