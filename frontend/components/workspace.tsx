"use client";

import { ChartNoAxesCombined, Compass, FolderOpen, LayoutGrid, LogOut, Scale, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, type Filters, type Niche, type Schema } from "@/lib/api";
import { filterQuery } from "@/lib/format";
import { useResource } from "@/lib/resource";
import { Failure, Loading } from "./states";

type Session = Schema<"Session">;
type Workspace = {
  session: Session | null | undefined;
  sessionError: unknown;
  retrySession: () => void;
  authenticate: (session: Session | null) => void;
  picked: Niche[];
  toggle: (niche: Niche) => void;
  clear: () => void;
};

const Context = createContext<Workspace | null>(null);
const loadSession = async (signal: AbortSignal) => {
  try {
    return await api("get", "/session", { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
};

export function useWorkspace() {
  const workspace = useContext(Context);
  if (!workspace) throw new Error("WorkspaceProvider is required");
  return workspace;
}

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const initial = useResource(loadSession);
  const [override, setOverride] = useState<Session | null>();
  const [picked, setPicked] = useState<Niche[]>([]);

  useEffect(() => {
    const expire = () => { setOverride(null); setPicked([]); };
    window.addEventListener("enot:session-expired", expire);
    return () => window.removeEventListener("enot:session-expired", expire);
  }, []);

  function authenticate(session: Session | null) {
    setOverride(session);
    setPicked([]);
  }

  function toggle(niche: Niche) {
    setPicked((current) => {
      if (current.some((item) => item.id === niche.id && item.dataset_id === niche.dataset_id)) {
        return current.filter(({ id }) => id !== niche.id);
      }
      return current.length < 5 && current.every(({ dataset_id, score }) =>
        dataset_id === niche.dataset_id && score.model_version === niche.score.model_version)
        ? [...current, niche] : current;
    });
  }

  return (
    <Context.Provider value={{
      session: override === undefined ? initial.data : override,
      sessionError: override === undefined ? initial.error : undefined,
      retrySession: initial.retry,
      authenticate, picked, toggle, clear: () => setPicked([]),
    }}>{children}</Context.Provider>
  );
}

export function Brand({ href = "/" }: { href?: string }) {
  return <Link href={href} className="brand"><span className="brand-icon"><ChartNoAxesCombined size={21} /></span><span>ENOT <small>Business Platform</small></span></Link>;
}

const navigation = [
  { href: "/", label: "Обзор", Icon: Compass },
  { href: "/niches", label: "Каталог ниш", Icon: LayoutGrid },
  { href: "/compare", label: "Сравнение", Icon: Scale },
  { href: "/research", label: "Исследования", Icon: FolderOpen },
];

export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const { session, sessionError, retrySession, authenticate, picked } = useWorkspace();
  const [logoutError, setLogoutError] = useState<unknown>();
  const [leaving, setLeaving] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (session === null) {
      const returnTo = window.location.pathname + window.location.search;
      router.replace(`/login?returnTo=${encodeURIComponent(returnTo)}`);
    }
  }, [router, session]);

  async function logout() {
    if (!session || leaving) return;
    setLeaving(true);
    setLogoutError(undefined);
    try {
      await api("delete", "/session", { csrf: session.csrf_token });
      authenticate(null);
      router.replace("/login");
    } catch (error) {
      setLogoutError(error);
    } finally {
      setLeaving(false);
    }
  }

  if (!session) {
    return <main className="auth-screen">{sessionError ? <Failure error={sessionError} retry={retrySession} /> : <Loading label="Проверяем сессию…" />}</main>;
  }

  return (
    <div className="shell">
      <a className="skip" href="#content">К содержанию</a>
      <aside className="sidebar">
        <Brand />
        <nav aria-label="Основная навигация">
          {navigation.map(({ href, label, Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");
            return <Link key={href} href={href} className="nav-item" aria-current={active ? "page" : undefined}><Icon size={19} /><span>{label}</span>{href === "/compare" && picked.length > 0 && <span className="nav-count">{picked.length}</span>}</Link>;
          })}
        </nav>
        <button className="nav-item logout" type="button" onClick={logout} disabled={leaving}><LogOut size={19} /><span>{leaving ? "Выходим…" : "Выйти"}</span></button>
      </aside>
      <main id="content" className="main" tabIndex={-1}>
        {logoutError ? <Failure error={logoutError} retry={logout} /> : null}
        {children}
      </main>
    </div>
  );
}

export function SelectNiche({ niche }: { niche: Niche }) {
  const { picked, toggle } = useWorkspace();
  const checked = picked.some(({ id, dataset_id }) => id === niche.id && dataset_id === niche.dataset_id);
  const different = picked.some(({ dataset_id, score }) =>
    dataset_id !== niche.dataset_id || score.model_version !== niche.score.model_version);
  const reason = checked ? null : different ? "Выберите ниши из одного выпуска и модели" : picked.length >= 5 ? "Выбрано 5 ниш" : null;

  return <div className="select-niche"><label className="check"><input type="checkbox" checked={checked} disabled={!!reason} onChange={() => toggle(niche)} aria-label={`Сравнить: ${niche.title}`} />Сравнить</label>{reason && <small>{reason}</small>}</div>;
}

export function CompareBar({ filters }: { filters: Filters }) {
  const { picked, clear } = useWorkspace();
  if (!picked.length) return null;
  const query = filterQuery(filters);
  return <aside className="compare-bar" aria-label="Выбор для сравнения"><div><strong aria-live="polite">Выбрано ниш {picked.length} из 5</strong><small>{picked.length === 1 ? "Выберите ещё одну нишу" : "Можно сравнить выбранные ниши"}</small></div><button className="button subtle" onClick={clear}>Очистить</button>{picked.length >= 2 && <Link className="button primary" href={query.size ? `/compare?${query}` : "/compare"}>К сравнению <ArrowUpRight size={16} /></Link>}</aside>;
}
