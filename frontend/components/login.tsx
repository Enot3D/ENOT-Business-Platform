"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { PasswordField } from "./account-fields";
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
    if (url.origin === origin && /^\/(?:$|(?:niches|research|compare|profile)(?:\/|$))/.test(url.pathname)) {
      return url.pathname + url.search;
    }
  } catch {
    // Malformed addresses fall back to the home page.
  }
  return "/";
}

export function Login({ returnTo }: { returnTo?: string }) {
  const router = useRouter();
  const { session, sessionError, retrySession, authenticate } = useWorkspace();
  const target = destination(returnTo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();

  useEffect(() => { if (session) router.replace(target); }, [router, session, target]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const fields = new FormData(event.currentTarget);
    setBusy(true);
    setError(undefined);
    try {
      const loggedIn = await api("post", "/session", {
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
    <div className="login-title"><ShieldCheck size={25} /><h1>Вход в платформу</h1><p>Доступ к каталогу ниш и сохранённым исследованиям.</p></div>
    {sessionError ? <Failure error={sessionError} retry={retrySession} /> : session === undefined || session ? <Loading label="Проверяем сессию…" /> :
      <form className="form-stack" onSubmit={submit}>
        {error ? <Failure error={error} /> : null}
        <label>Электронная почта или логин<input name="login" inputMode="email" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={254} /></label>
        <PasswordField label="Пароль" name="password" autoComplete="current-password" />
        <button className="button primary" disabled={busy}>{busy ? "Входим…" : "Войти"} <ArrowRight size={17} /></button>
        <Link className="text-link" href="/register">Зарегистрироваться</Link>
      </form>}
  </section></main>;
}
