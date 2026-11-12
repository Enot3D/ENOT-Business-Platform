"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { useResource } from "@/lib/resource";
import { PasswordField, passwordHint, passwordIssue } from "./account-fields";
import { Failure, Loading } from "./states";
import { useWorkspace } from "./workspace";

const loadProfile = (signal: AbortSignal) => api("get", "/profile", { signal });

export function Profile() {
  const profile = useResource(loadProfile);
  const { session, renewSession } = useWorkspace();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<unknown>();

  async function submit(event: FormEvent<HTMLFormElement>, changePassword = false) {
    event.preventDefault();
    if (!session || pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const csrf = session.csrf_token;
    setError(undefined);
    setMessage("");
    setPending(true);
    try {
      if (changePassword) {
        const password = String(fields.get("password"));
        const issue = passwordIssue(password, String(fields.get("confirmation")));
        if (issue) {
          setMessage(issue);
          return;
        }
        renewSession(await api("post", "/profile/password", {
          csrf, body: { password, current_password: String(fields.get("current_password")) },
        }));
        form.reset();
        setMessage("Пароль изменён.");
      } else {
        await api("patch", "/profile", { csrf, body: { name: String(fields.get("name")) } });
        profile.retry();
        setMessage("Имя сохранено.");
      }
    } catch (error) {
      setError(error);
    } finally {
      setPending(false);
    }
  }

  return <>
    <header className="page-heading"><div><h1>Личный кабинет</h1></div></header>
    {message && <p className="panel content-panel" role="status">{message}</p>}
    {error ? <Failure error={error} /> : null}
    {profile.pending && <Loading />}
    {profile.error ? <Failure error={profile.error} retry={profile.retry} /> : null}
    {profile.data && <section className="panel content-panel account-panel">
      <h2>Данные аккаунта</h2>
      <form className="form-stack" onSubmit={submitName => submit(submitName)}>
        <label>Имя пользователя<input name="name" defaultValue={profile.data.name} maxLength={80} required /></label>
        <p className="muted">Электронная почта</p>
        <p>{profile.data.email ?? "Не указана"}</p>
        <button className="button primary" disabled={pending}>Сохранить имя</button>
      </form>
    </section>}
    <section className="panel content-panel account-panel">
      <h2>Сменить пароль</h2>
      <form className="form-stack" onSubmit={event => submit(event, true)}>
        <PasswordField label="Текущий пароль" name="current_password" autoComplete="current-password" />
        <PasswordField label="Новый пароль" name="password" autoComplete="new-password" />
        <small className="muted">{passwordHint}</small>
        <PasswordField label="Подтверждение пароля" name="confirmation" autoComplete="new-password" />
        <button className="button primary" disabled={pending}>Сменить пароль</button>
      </form>
    </section>
  </>;
}
