import Link from "next/link";

export function SiteHeader({ current }: { current?: "statistics" }) {
  return (
    <header className="site-header">
      <Link aria-label="AeroAndes, inicio" className="brand" href="/">
        <span aria-hidden="true" className="brand-symbol">
          A
        </span>
        <span className="brand-name">
          aero<span>andes</span>
        </span>
      </Link>

      <nav aria-label="Navegación principal" className="main-nav">
        <Link href="/#buscar">Vuelos</Link>
        <Link href="/#beneficios">Cómo funciona</Link>
        <Link aria-current={current === "statistics" ? "page" : undefined} href="/estadisticas">Estadísticas</Link>
        <span className="nav-note">Reservas en tiempo real</span>
      </nav>
    </header>
  );
}
