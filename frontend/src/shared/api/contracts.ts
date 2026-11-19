import type { Flight } from "@/features/flight-search/model/types";

export type FlightSearchResponse = {
  data: Flight[];
  pagination: {
    page: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
  };
};

export type FlightSeat = {
  seatNumber: string;
  status: "AVAILABLE" | "HELD" | "BOOKED" | "UNAVAILABLE";
};

export type FlightSeatsResponse = {
  flightId: string;
  seats: FlightSeat[];
};

export type CreateReservationResponse = {
  reservationId: string;
  status: "PENDING" | "CONFIRMED" | "FAILED" | "EXPIRED";
  flightId: string;
  seatNumber: string;
  amount: number | null;
  currency: string | null;
  expiresAt: string;
  accessToken?: string;
  correlationId?: string;
  replayed: boolean;
  accessCredentialAvailable: boolean;
};

export type ReservationStatus = {
  reservationId: string;
  status: "PENDING" | "CONFIRMED" | "FAILED" | "EXPIRED";
  flightId: string;
  seatNumber: string;
  amount: number | null;
  currency: string | null;
  expiresAt: string;
  bookingCode: string | null;
  failureReason: string | null;
  sequence: number;
};

export type ReservationEvent = {
  type: "reservation.updated";
  notificationId: string;
  sequence: number;
  status: ReservationStatus["status"];
  bookingCode: string | null;
  failureReason: string | null;
};

export function detailFromResponse(body: unknown, fallback: string): string {
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    return body.detail;
  }
  return fallback;
}
