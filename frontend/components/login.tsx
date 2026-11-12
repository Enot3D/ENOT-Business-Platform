"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Brand, useWorkspace } from "./workspace";
import { Failure, Loading } from "./states";

function destination(value?: string) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || /[\\\s]/.test(value)) {
    return "/";
  }

  const origin = "https://enot.invalid";
  try {
    const url = new URL(value, origin);
    if (url.origin === origin && /^\/(?:$|(?:niches|research|compare)(?:\/|$))/.test(url.pathname)) {
      return url.pathname + url.search;
    }
  } catch {
    // Malformed addresses fall back to the home page.
  }
  return "/";
}

export function Login({ returnTo }: { returnTo?: string }) {
  const router = useRouter();
  const { session, sessionError, authenticate } = useWorkspace();
  const target = destination(returnTo);
  const [busy, setBusy] = useState(false);
  const [firstAccount, setFirstAccount] = useState(false);
  const [error, setError] = useState<unknown>();

  useEffect(() => { if (session) router.replace(target); }, [router, session, target]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const fields = new FormData(event.currentTarget);
    setBusy(true);
    setError(undefined);
    try {
      const loggedIn = await api("post", (firstAccount ? "/bootstrap" : "/session"), {
        body: { login: String(fields.get("login")), password: String(fields.get("password")) },
      });
      authenticate(loggedIn);
      router.replace(target);
    } catch (error) {
      setError(error);
    } finally {
      setBusy(false);
    }
  }

  return <main className="auth-screen"><section className="login-card">
    <Brand href="/login" />
    <div className="login-title"><ShieldCheck size={25} /><h1>{firstAccount ? "Создать первый аккаунт" : "Вход в платформу"}</h1><p>Доступ к каталогу ниш и сохранённым исследованиям.</p></div>
    {session === undefined && !sessionError || session ? <Loading label="Проверяем сессию…" /> :
      <form className="form-stack" onSubmit={submit}>
        {error ? <Failure error={error} /> : null}
        <label>Логин<input name="login" autoComplete="username" required maxLength={128} /></label>
        <label>Пароль<input name="password" type="password" autoComplete="current-password" required maxLength={256} /></label>
        <button className="button primary" disabled={busy}>{busy ? "Подождите…" : firstAccount ? "Создать аккаунт и войти" : "Войти"} <ArrowRight size={17} /></button>
        <button type="button" className="button" disabled={busy} onClick={() => { setFirstAccount(!firstAccount); setError(undefined); }}>{firstAccount ? "Уже есть аккаунт? Войти" : "Первый запуск? Создать аккаунт"}</button>
      </form>}
  </section></main>;
}
