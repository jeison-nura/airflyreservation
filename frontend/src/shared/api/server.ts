import type { FlightSearchResponse } from "./contracts";
import type { FlightSearchCriteria } from "@/features/flight-search/model/types";

const backendBaseUrl = (
  process.env.BACKEND_API_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

export async function searchFlights(
  criteria: FlightSearchCriteria,
  { page = 1, pageSize = 100 } = {},
): Promise<FlightSearchResponse> {
  const query = new URLSearchParams({
    origin: criteria.origin,
    destination: criteria.destination,
    departureDate: criteria.departureDate,
    page: String(page),
    pageSize: String(pageSize),
  });
  const response = await fetch(`${backendBaseUrl}/inventory/flights?${query}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) {
    throw new Error(`BACKEND_HTTP_${response.status}`);
  }
  return (await response.json()) as FlightSearchResponse;
}
