import Link from "next/link";
import { ArrowRight, ChartNoAxesCombined, FolderOpen, Scale } from "lucide-react";

export default function Home() {
  return <>
    <header className="page-heading"><h1>Обзор</h1></header>
    <section className="hero">
      <div><p className="eyebrow">Аналитика бизнес-ниш</p>
        <h2>Выберите нишу<br />для проверки спроса</h2>
        <p>Изучите данные рынка, сравните оценки и сохраните выводы со ссылками на источники.</p>
        <Link className="button primary" href="/niches">Открыть каталог <ArrowRight size={18} /></Link>
      </div>
      <div className="hero-art" aria-hidden="true"><ChartNoAxesCombined /></div>
    </section>
    <div className="home-links">
      <Link href="/compare" className="panel home-link"><span className="feature-icon"><Scale size={22} /></span><span><strong>Сравнение ниш</strong><small>Диапазоны оценок и финансовые сценарии</small></span><ArrowRight size={17} /></Link>
      <Link href="/research" className="panel home-link"><span className="feature-icon"><FolderOpen size={22} /></span><span><strong>Мои исследования</strong><small>Сохранённые отчёты и история версий</small></span><ArrowRight size={17} /></Link>
    </div>
  </>;
}
