 "use client";

import { useState } from "react";

import { BookingFlow } from "@/features/booking/ui/booking-flow";
import { formatFlightDate } from "../model/format-flight-date.ts";
import type { Flight } from "../model/types.ts";
import { FlightCard } from "./flight-card.tsx";

type FlightResultsProps = {
  flights: Flight[];
  origin: string;
  destination: string;
  departureDate: string;
  searchError?: string;
};

export function FlightResults({
  flights,
  origin,
  destination,
  departureDate,
  searchError = "",
}: FlightResultsProps) {
  const [selectedFlight, setSelectedFlight] = useState<Flight | null>(null);

  if (selectedFlight) {
    return (
      <BookingFlow
        flight={selectedFlight}
        onCancel={() => setSelectedFlight(null)}
      />
    );
  }

  return (
    <section aria-labelledby="results-heading" className="results-section" id="results">
      <div className="section-heading">
        <div>
          <p className="eyebrow">TU VIAJE COMIENZA AQUÍ</p>
          <h2 id="results-heading">Vuelos disponibles</h2>
          <p className="results-route">
            {origin} <span aria-hidden="true">→</span> {destination}
            <span className="results-date">{formatFlightDate(departureDate)}</span>
          </p>
        </div>
        <p aria-live="polite" className="result-count">
          {flights.length} {flights.length === 1 ? "opción" : "opciones"}
        </p>
      </div>

      {searchError ? (
        <div className="search-error" role="alert">{searchError}</div>
      ) : flights.length > 0 ? (
        <div className="flight-list">
          {flights.map((flight) => (
            <FlightCard
              flight={flight}
              key={flight.id}
              onSelect={setSelectedFlight}
            />
          ))}
        </div>
      ) : (
        <div className="empty-results" role="status">
          <span aria-hidden="true" className="empty-icon">⌕</span>
          <h3>No encontramos vuelos para esta búsqueda</h3>
          <p>Prueba con otra fecha o cambia el origen y el destino.</p>
        </div>
      )}
    </section>
  );
}
