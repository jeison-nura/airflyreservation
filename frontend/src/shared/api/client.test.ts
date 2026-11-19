import { afterEach, expect, jest, test } from "@jest/globals";
import { confirmReservation, createReservation, getFlightSeats, getReservation } from "./client";

afterEach(() => { jest.restoreAllMocks(); });

test("loads public seats without caching or credentials", async () => {
  const seats = [{ seatNumber: "1A", status: "HELD" }];
  const fetchMock = jest.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ seats }));
  await expect(getFlightSeats("flight/204")).resolves.toEqual(seats);
  expect(fetchMock).toHaveBeenCalledWith("/api/backend/inventory/flights/flight%2F204/seats", {
    cache: "no-store",
    headers: {},
  });
});

test("sends the idempotency key separately from the reservation request and reports seat conflicts", async () => {
  const fetchMock = jest.spyOn(globalThis, "fetch")
    .mockResolvedValue(Response.json({ detail: "SEAT_UNAVAILABLE" }, { status: 409 }));
  const passenger = { fullName: "Pasajera Prueba", email: "qa@example.test" };
  await expect(createReservation({
    flightId: "flight-204", seatNumber: "1A", passenger, idempotencyKey: "test-key",
  })).rejects.toThrow("SEAT_UNAVAILABLE");
  expect(fetchMock).toHaveBeenCalledWith("/api/backend/reservations", expect.objectContaining({
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": "test-key" },
    body: JSON.stringify({ flightId: "flight-204", seatNumber: "1A", passenger }),
  }));
});

test("queries and confirms a private reservation without placing the token in the URL", async () => {
  const fetchMock = jest.spyOn(globalThis, "fetch")
    .mockImplementation(async () => Response.json({ status: "CONFIRMED" }));
  await getReservation("reservation/1", "demo-token");
  await confirmReservation("reservation/1", "demo-token", "confirm-key");
  expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/backend/reservations/reservation%2F1",
    expect.objectContaining({ headers: { Authorization: "Bearer demo-token" } }));
  expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/backend/reservations/reservation%2F1/confirm",
    expect.objectContaining({
      method: "POST",
      headers: { Authorization: "Bearer demo-token", "Idempotency-Key": "confirm-key" },
    }));
});

test("falls back to the HTTP status for a non-JSON upstream error", async () => {
  jest.spyOn(globalThis, "fetch").mockResolvedValue(new Response("Unavailable", { status: 503 }));
  await expect(getFlightSeats("flight-204")).rejects.toThrow("HTTP_503");
});
