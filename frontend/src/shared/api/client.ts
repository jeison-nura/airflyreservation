import type {
  CreateReservationResponse,
  FlightSeat,
  FlightSeatsResponse,
  ReservationStatus,
} from "./contracts";
import { detailFromResponse } from "./contracts";

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(detailFromResponse(body, `HTTP_${response.status}`));
  }
  return body as T;
}

export async function getFlightSeats(flightId: string): Promise<FlightSeat[]> {
  const result = await request<FlightSeatsResponse>(
    `inventory/flights/${encodeURIComponent(flightId)}/seats`,
  );
  return result.seats;
}

export function createReservation(input: {
  flightId: string;
  seatNumber: string;
  passenger: { fullName: string; email: string };
  idempotencyKey: string;
}): Promise<CreateReservationResponse> {
  return request("reservations", {
    method: "POST",
    headers: { "Idempotency-Key": input.idempotencyKey },
    body: JSON.stringify({
      flightId: input.flightId,
      seatNumber: input.seatNumber,
      passenger: input.passenger,
    }),
  });
}

export function confirmReservation(
  reservationId: string,
  accessToken: string,
  idempotencyKey: string,
): Promise<ReservationStatus> {
  return request(`reservations/${encodeURIComponent(reservationId)}/confirm`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Idempotency-Key": idempotencyKey,
    },
  });
}

export function getReservation(
  reservationId: string,
  accessToken: string,
): Promise<ReservationStatus> {
  return request(`reservations/${encodeURIComponent(reservationId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export function apiWebSocketBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_WS_URL;
  if (configured) return configured.replace(/\/$/, "");
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//localhost:8000/api/v1`;
}
