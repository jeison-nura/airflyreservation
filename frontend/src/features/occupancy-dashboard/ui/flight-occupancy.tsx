"use client";

import { useEffect, useState } from "react";
import type { Flight } from "@/features/flight-search/model/types";
import type { FlightSeat } from "@/shared/api/contracts";
import { observeFlightSeats } from "@/shared/api/observe-flight-seats";
import { summarizeOccupancy } from "../model/occupancy";

const statuses = { ON_TIME: "A tiempo", DELAYED: "Retrasado", CANCELLED: "Cancelado" };

export function FlightOccupancy({ flight }: { flight: Flight }) {
  const [seats, setSeats] = useState<FlightSeat[] | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    const observer = observeFlightSeats(flight.id, (next) => {
      setSeats(next);
      setUnreachable(false);
    }, () => setUnreachable(true));
    return observer.stop;
  }, [flight.id]);

  const counts = seats && summarizeOccupancy(seats);
  const percent = counts?.capacity ? Math.round(100 * counts.BOOKED / counts.capacity) : 0;

  return (
    <article className="occupancy-card" aria-labelledby={`occupancy-${flight.id}`}>
      <div className="occupancy-card-heading">
        <div>
          <p className="eyebrow">{flight.airline}</p>
          <h2 id={`occupancy-${flight.id}`}>Vuelo {flight.flightNumber}</h2>
        </div>
        <p className="result-count">{statuses[flight.status]}</p>
      </div>
      <p className="results-route">
        {flight.origin.code} {flight.origin.time} → {flight.destination.code} {flight.destination.time}
      </p>
      {unreachable && (
        <p role="status">
          {counts ? "Mostramos los últimos datos recibidos." : "No pudimos consultar los asientos."} Reintentando…
        </p>
      )}
      {!counts && !unreachable && <p role="status">Consultando asientos…</p>}
      {counts && (
        <>
          <dl className="occupancy-metrics">
            <div><dt>Disponibles</dt><dd>{counts.AVAILABLE}</dd></div>
            <div><dt>Bloqueados</dt><dd>{counts.HELD}</dd></div>
            <div><dt>Confirmados</dt><dd>{counts.BOOKED}</dd></div>
          </dl>
          {counts.capacity > 0 ? (
            <div className="occupancy-progress">
              <label htmlFor={`progress-${flight.id}`}>Ocupación confirmada: {percent}%</label>
              <meter id={`progress-${flight.id}`} max={counts.capacity} value={counts.BOOKED} />
              <p>{counts.BOOKED} de {counts.capacity} plazas habilitadas</p>
            </div>
          ) : <p>No hay plazas habilitadas para este vuelo.</p>}
          {counts.UNAVAILABLE > 0 && <p className="occupancy-excluded">Fuera de servicio: {counts.UNAVAILABLE}</p>}
        </>
      )}
    </article>
  );
}
