import Link from "next/link";
import type { Metadata } from "next";
import { Suspense } from "react";
import { FlightSearchForm } from "@/features/flight-search/ui/flight-search-form";
import { airports } from "@/features/flight-search/data/demo-flights";
import { FlightOccupancy } from "@/features/occupancy-dashboard/ui/flight-occupancy";
import { searchFlights } from "@/shared/api/server";
import { SiteHeader } from "@/shared/ui/site-header";

export const metadata: Metadata = { title: "Estadísticas de vuelos | AeroAndes" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

async function StatisticsResults({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const params = await searchParams;
  const origin = typeof params.origin === "string" ? params.origin : "BOG";
  const destination = typeof params.destination === "string" ? params.destination : "MDE";
  const departureDate = typeof params.departureDate === "string" ? params.departureDate : "2026-11-19";
  const rawPage = typeof params.page === "string" ? Number(params.page) : 1;
  const page = Number.isSafeInteger(rawPage) && rawPage >= 1 ? rawPage : 1;
  const date = new Date(`${departureDate}T00:00:00Z`);
  const valid = origin !== destination &&
    [origin, destination].every((code) => airports.some((airport) => airport.code === code)) &&
    !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === departureDate;
  const criteria = { origin, destination, departureDate };
  const result = valid ? await searchFlights(criteria, { page, pageSize: 12 }).catch(() => null) : null;

  function pageLink(next: number) {
    return `/estadisticas?${new URLSearchParams({ ...criteria, page: String(next) })}`;
  }

  return (
    <>
      <div className="search-panel">
        <FlightSearchForm {...criteria} action="/estadisticas" />
      </div>
      {!valid ? (
        <p className="search-error" role="alert">Elige dos aeropuertos distintos y una fecha válida.</p>
      ) : !result ? (
        <p className="search-error" role="alert">No pudimos consultar los vuelos. Intenta buscar de nuevo.</p>
      ) : result.data.length === 0 ? (
        <div className="empty-results">
          {page === 1 ? "No hay vuelos para esta ruta y fecha." : (
            <Link href={pageLink(1)}>Esta página no tiene vuelos. Volver a la primera página.</Link>
          )}
        </div>
      ) : (
        <section className="occupancy-results" aria-label="Ocupación por vuelo">
          <p>
            {result.pagination.totalItems} {result.pagination.totalItems === 1 ? "vuelo" : "vuelos"}
            {" · Bloqueados: retenciones temporales · Confirmados: plazas asignadas en inventario"}
          </p>
          <div className="occupancy-grid">
            {result.data.map((flight) => <FlightOccupancy key={flight.id} flight={flight} />)}
          </div>
          {result.pagination.totalPages > 1 && (
            <nav aria-label="Páginas de vuelos" className="booking-actions">
              {page > 1 && <Link className="button button-secondary" href={pageLink(page - 1)}>Anterior</Link>}
              {page < result.pagination.totalPages && (
                <Link className="button button-secondary" href={pageLink(page + 1)}>Siguiente</Link>
              )}
            </nav>
          )}
        </section>
      )}
    </>
  );
}

export default function StatisticsPage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <>
      <a className="skip-link" href="#main-content">Saltar al contenido</a>
      <SiteHeader current="statistics" />
      <main className="page-shell occupancy-page" id="main-content">
        <div className="section-heading">
          <div>
            <p className="eyebrow">INVENTARIO DE VUELOS</p>
            <h1>Estadísticas de ocupación</h1>
            <p className="results-route">Consulta el estado de los asientos por ruta y fecha. Los datos se actualizan automáticamente.</p>
          </div>
        </div>
        <Suspense fallback={<p role="status">Consultando vuelos…</p>}>
          <StatisticsResults searchParams={searchParams} />
        </Suspense>
      </main>
    </>
  );
}
