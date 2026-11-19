import type { Flight, FlightSearchCriteria } from "./types.ts";

export function searchFlights(
  flights: readonly Flight[],
  criteria: FlightSearchCriteria,
): Flight[] {
  const origin = criteria.origin.trim().toUpperCase();
  const destination = criteria.destination.trim().toUpperCase();

  return flights.filter(
    (flight) =>
      flight.origin.code === origin &&
      flight.destination.code === destination &&
      flight.departureDate === criteria.departureDate &&
      flight.availableSeats > 0 &&
      flight.status !== "CANCELLED",
  );
}
