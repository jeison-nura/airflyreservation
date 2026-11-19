import { Suspense } from "react";

import { airports } from "@/features/flight-search/data/demo-flights";
import type { Flight } from "@/features/flight-search/model/types";
import { searchFlights as searchInventoryFlights } from "@/shared/api/server";
import { FlightResults } from "@/features/flight-search/ui/flight-results";
import { FlightSearchForm } from "@/features/flight-search/ui/flight-search-form";
import { SiteHeader } from "@/shared/ui/site-header";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const DEMO_DEPARTURE_DATE = "2026-11-19";

function readParam(value: string | string[] | undefined) {
  return typeof value === "string" ? value.trim() : "";
}

function isValidDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;

  const parsedDate = new Date(`${value}T00:00:00.000Z`);
  return (
    !Number.isNaN(parsedDate.getTime()) &&
    parsedDate.toISOString().slice(0, 10) === value
  );
}

async function SearchResults({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const rawOrigin = readParam(params.origin).toUpperCase();
  const rawDestination = readParam(params.destination).toUpperCase();
  const rawDepartureDate = readParam(params.departureDate);
  const hasSearch = Boolean(rawOrigin || rawDestination || rawDepartureDate);

  const origin = airports.find((airport) => airport.code === rawOrigin);
  const destination = airports.find(
    (airport) => airport.code === rawDestination,
  );
  const isValidSearch =
    !hasSearch ||
    (Boolean(origin) &&
      Boolean(destination) &&
      rawOrigin !== rawDestination &&
      isValidDate(rawDepartureDate));

  if (!hasSearch) return null;

  if (!isValidSearch) {
    return (
      <p className="search-error page-shell" role="alert">
        Revisa el origen, el destino y la fecha. Deben ser válidos y diferentes.
      </p>
    );
  }

  let flights: Flight[] = [];
  let searchError = "";
  try {
    const result = await searchInventoryFlights({
      origin: rawOrigin,
      destination: rawDestination,
      departureDate: rawDepartureDate,
    });
    flights = result.data;
  } catch {
    searchError =
      "No pudimos conectar con el servicio de vuelos. Verifica que el backend esté disponible e inténtalo de nuevo.";
  }

  return (
    <FlightResults
      departureDate={rawDepartureDate}
      destination={destination?.city ?? rawDestination}
      flights={flights}
      origin={origin?.city ?? rawOrigin}
      searchError={searchError}
    />
  );
}

export default function Home({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  return (
    <>
      <a className="skip-link" href="#main-content">
        Saltar al contenido
      </a>
      <SiteHeader />

      <main className="page-shell" id="main-content">
        <section aria-labelledby="hero-heading" className="hero" id="buscar">
          <div className="hero-copy">
            <p className="eyebrow">VIAJAR, A TU MANERA</p>
            <h1 id="hero-heading">
              Hay un lugar
              <br />
              <span>esperándote.</span>
            </h1>
            <p className="hero-description">
              Encuentra el vuelo ideal, consulta la disponibilidad y protege tu
              asiento al confirmar la reserva.
            </p>
          </div>

          <div className="search-panel">
            <div className="search-panel-heading">
              <h2>Encuentra tu vuelo</h2>
              <span>Solo vuelos directos</span>
            </div>

            <FlightSearchForm
              departureDate={DEMO_DEPARTURE_DATE}
              destination="MDE"
              origin="BOG"
            />
          </div>
        </section>

        <Suspense fallback={null}>
          <SearchResults searchParams={searchParams} />
        </Suspense>

        <section
          aria-labelledby="how-it-works-heading"
          className="benefits"
          id="beneficios"
        >
          <div className="how-it-works-heading">
            <p className="eyebrow">CÓMO FUNCIONA</p>
            <h2 id="how-it-works-heading">Un recorrido sencillo, paso a paso</h2>
              <p>Consulta la disponibilidad del servidor y confirma tu reserva desde un solo flujo.</p>
          </div>
          <article className="benefit">
            <span aria-hidden="true" className="benefit-icon">
              1
            </span>
            <div>
              <h3>Busca vuelos</h3>
              <p>Elige ruta y fecha para consultar las tarifas y horarios del inventario.</p>
            </div>
          </article>
          <article className="benefit">
            <span aria-hidden="true" className="benefit-icon">
              2
            </span>
            <div>
              <h3>Elige un asiento</h3>
              <p>El mapa consulta Inventory y el asiento se bloquea al crear la reserva.</p>
            </div>
          </article>
          <article className="benefit">
            <span aria-hidden="true" className="benefit-icon">
              3
            </span>
            <div>
              <h3>Revisa los datos</h3>
              <p>Completa nombre y correo; Payments ficticio autoriza y confirma la compra.</p>
            </div>
          </article>
          <p className="frontend-note">
            <strong>Por dentro:</strong> Next.js consulta Inventory desde el servidor; un proxy same-origin conecta el navegador con reservas y asientos. La credencial de acceso permanece en memoria y WebSocket notifica los cambios de estado.
          </p>
        </section>
      </main>

      <footer className="site-footer">
        AeroAndes · Experiencia de demostración para reservas de vuelos
      </footer>
    </>
  );
}
