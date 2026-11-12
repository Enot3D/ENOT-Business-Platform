"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { PasswordField, passwordHint, passwordIssue } from "./account-fields";
import { Failure, Loading } from "./states";
import { Brand, useWorkspace } from "./workspace";

export function Register() {
  const router = useRouter();
  const { session, sessionError, retrySession, authenticate } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [issue, setIssue] = useState("");
  const [error, setError] = useState<unknown>();

  useEffect(() => { if (session) router.replace("/"); }, [router, session]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const fields = new FormData(event.currentTarget);
    const name = String(fields.get("name")).trim();
    const password = String(fields.get("password"));
    const problem = !name ? "Введите имя пользователя." : passwordIssue(password, String(fields.get("confirmation")));
    setError(undefined);
    setIssue(problem);
    if (problem) return;
    setBusy(true);
    try {
      authenticate(await api("post", "/register", { body: {
        name, email: String(fields.get("email")).trim(), password,
      } }));
      router.replace("/");
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }

  return <main className="auth-screen"><section className="login-card">
    <Brand href="/login" />
    <div className="login-title"><h1>Регистрация</h1></div>
    {sessionError ? <Failure error={sessionError} retry={retrySession} /> : session === undefined || session ?
      <Loading label="Проверяем сессию…" /> :
      <form className="form-stack" onSubmit={submit}>
        {issue && <p className="state state-error" role="alert">{issue}</p>}
        {error ? <Failure error={error} /> : null}
        <label>Имя пользователя<input name="name" autoComplete="nickname" required maxLength={80} /></label>
        <label>Электронная почта<input name="email" type="email" autoComplete="email" autoCapitalize="none" spellCheck={false} required maxLength={254} /></label>
        <PasswordField label="Пароль" name="password" autoComplete="new-password" />
        <small className="muted">{passwordHint}</small>
        <PasswordField label="Подтверждение пароля" name="confirmation" autoComplete="new-password" />
        <button className="button primary" disabled={busy}>{busy ? "Создаём аккаунт…" : "Зарегистрироваться"}</button>
        <Link className="text-link" href="/login">Уже есть аккаунт? Войти</Link>
      </form>}
  </section></main>;
}
