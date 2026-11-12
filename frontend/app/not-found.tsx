import Link from "next/link";

export default function NotFound() {
  return <main className="auth-screen"><section className="login-card"><h1>Страница недоступна</h1><Link className="button primary" href="/">Вернуться на главную</Link></section></main>;
}
