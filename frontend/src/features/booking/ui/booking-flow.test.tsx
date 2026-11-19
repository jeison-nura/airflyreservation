/** @jest-environment jsdom */

import { afterEach, beforeAll, beforeEach, expect, jest, test } from "@jest/globals";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { Flight } from "@/features/flight-search/model/types";
import type { confirmReservation, createReservation, getReservation } from "@/shared/api/client";
import type { FlightSeat } from "@/shared/api/contracts";
import type { observeFlightSeats } from "@/shared/api/observe-flight-seats";

const observe = jest.fn<typeof observeFlightSeats>();
const create = jest.fn<typeof createReservation>();
const confirm = jest.fn<typeof confirmReservation>();
const readReservation = jest.fn<typeof getReservation>();
const socketBaseUrl = jest.fn<() => string>();
const pending = {
  reservationId: "reservation-1",
  flightId: "flight-204",
  seatNumber: "1A",
  amount: 189900,
  currency: "COP",
  expiresAt: "2026-11-19T17:30:00Z",
  status: "PENDING" as const,
};
let BookingFlow: typeof import("./booking-flow").BookingFlow;

beforeAll(async () => {
  jest.doMock("@/shared/api/observe-flight-seats", () => ({ observeFlightSeats: observe }));
  jest.doMock("@/shared/api/client", () => ({
    createReservation: create,
    confirmReservation: confirm,
    getReservation: readReservation,
    apiWebSocketBaseUrl: socketBaseUrl,
  }));
  ({ BookingFlow } = await import("./booking-flow"));
});

const flight: Flight = {
  id: "flight-204",
  flightNumber: "AA 204",
  airline: "AeroAndes",
  origin: { code: "BOG", city: "Bogotá", time: "07:10" },
  destination: { code: "MDE", city: "Medellín", time: "08:05" },
  departureDate: "2026-11-19",
  duration: "55 min",
  price: 189900,
  currency: "COP",
  availableSeats: 1,
  status: "ON_TIME",
};
const available: FlightSeat[] = [{ seatNumber: "1A", status: "AVAILABLE" }];
const held: FlightSeat[] = [{ seatNumber: "1A", status: "HELD" }];
const booked: FlightSeat[] = [{ seatNumber: "1A", status: "BOOKED" }];

beforeEach(() => {
  jest.useFakeTimers();
  socketBaseUrl.mockImplementation(() => { throw new Error("WebSocket disabled in unit test"); });
  observe.mockReturnValue({ refresh: async () => {}, stop: jest.fn() });
});

afterEach(() => {
  cleanup();
  jest.useRealTimers();
  jest.resetAllMocks();
  jest.restoreAllMocks();
});

function openBooking() {
  render(<BookingFlow flight={flight} onCancel={jest.fn()} />);
  const [, receiveSeats] = observe.mock.calls[0];
  return (next: FlightSeat[], previous: FlightSeat[]) =>
    act(() => receiveSeats(next, previous));
}

test("shows a notice for a new hold and dismisses it at 7000 ms without repeating on confirmation", () => {
  const receive = openBooking();
  receive(available, []);
  receive(held, available);
  expect(screen.getByRole("alert").textContent).toContain("El asiento 1A ya no está disponible.");
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Asiento 1A, held" }).disabled)
    .toBe(true);

  act(() => { jest.advanceTimersByTime(6_999); });
  expect(screen.queryByRole("alert")).not.toBeNull();
  receive(booked, held);
  act(() => { jest.advanceTimersByTime(1); });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Asiento 1A, booked" }).disabled)
    .toBe(true);
});

test("a lost selection returns to the map and permits manual dismissal", () => {
  const receive = openBooking();
  receive(available, []);
  fireEvent.click(screen.getByRole("button", { name: "Asiento 1A, disponible" }));
  fireEvent.click(screen.getByRole("button", { name: "Continuar con asiento 1A" }));
  expect(screen.getByRole("heading", { name: "Pasajero y facturación" })).toBeTruthy();

  receive(held, available);
  expect(screen.getByRole("heading", { name: "Elige tu asiento" })).toBeTruthy();
  const alert = screen.getByRole("alert");
  expect(alert.textContent).toContain("Elige otro para continuar.");
  fireEvent.click(within(alert).getByRole("button", { name: "Cerrar notificación" }));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Continuar con el pasajero" }).disabled)
    .toBe(true);
});

function fillPassengerForm() {
  const receive = openBooking();
  receive(available, []);
  fireEvent.click(screen.getByRole("button", { name: "Asiento 1A, disponible" }));
  fireEvent.click(screen.getByRole("button", { name: "Continuar con asiento 1A" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Nombre completo" }), {
    target: { value: "Pasajera Prueba" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Correo electrónico" }), {
    target: { value: "qa@example.test" },
  });
}

test("a conflict while creating the reservation restores the seat map with an alert", async () => {
  create.mockRejectedValue(new Error("SEAT_UNAVAILABLE"));
  fillPassengerForm();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Crear reserva" })); });
  expect(screen.getByRole("heading", { name: "Elige tu asiento" })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("El asiento 1A acaba de ser tomado");
});

test("confirms the fictitious purchase without exposing its access credential", async () => {
  const token = "demo-capability";
  create.mockResolvedValue({
    ...pending, accessToken: token,
    replayed: false, accessCredentialAvailable: true,
  });
  confirm.mockResolvedValue({
    ...pending, status: "CONFIRMED", bookingCode: "AF-DEMO", failureReason: null, sequence: 2,
  });
  fillPassengerForm();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Crear reserva" })); });
  expect(screen.getByRole("heading", { name: "Revisa tu reserva" })).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: /tarjeta/i })).toBeNull();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reserva" }));
  });
  expect(screen.getByRole("heading", { name: "¡Reserva confirmada!" })).toBeTruthy();
  expect(screen.getByText("AF-DEMO")).toBeTruthy();
  expect(confirm).toHaveBeenCalledWith("reservation-1", token, expect.any(String));
  expect(document.body.textContent).not.toContain(token);
});

test("refreshes private reservation status and ignores a stale WebSocket update", async () => {
  const socket = {
    send: jest.fn(),
    close: jest.fn(),
    onopen: undefined as (() => void) | undefined,
    onmessage: undefined as ((message: { data: string }) => void) | undefined,
  };
  const connect = jest.spyOn(globalThis, "WebSocket").mockImplementation(() =>
    socket as unknown as WebSocket);
  socketBaseUrl.mockReturnValue("ws://localhost:8000/api/v1");
  create.mockResolvedValue({
    ...pending, accessToken: "demo-capability", replayed: false, accessCredentialAvailable: true,
  });
  readReservation
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...pending, bookingCode: null, failureReason: null, sequence: 3 });
  fillPassengerForm();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Crear reserva" })); });
  expect(connect).toHaveBeenCalledWith("ws://localhost:8000/api/v1/reservations/reservation-1/events/ws");
  act(() => socket.onopen?.());
  expect(socket.send).toHaveBeenCalledWith(JSON.stringify({
    type: "subscribe", accessToken: "demo-capability", afterSequence: 1,
  }));

  await act(async () => { await jest.advanceTimersByTimeAsync(2_000); });
  expect(screen.getByRole("status").textContent).toContain("Reintentaremos");
  await act(async () => { await jest.advanceTimersByTimeAsync(2_000); });
  expect(readReservation).toHaveBeenCalledWith("reservation-1", "demo-capability");

  const expire = (sequence: number) => act(() => socket.onmessage?.({
    data: JSON.stringify({ type: "reservation.updated", status: "EXPIRED", sequence }),
  }));
  expire(2);
  expect(screen.getByRole("button", { name: "Confirmar reserva" })).toBeTruthy();
  expire(4);
  expect(screen.getByRole("button", { name: "Consultar estado" })).toBeTruthy();
  expect(socket.close).toHaveBeenCalledTimes(1);
});

test("does not recreate a credential when the server replays the creation request", async () => {
  create.mockResolvedValue({ ...pending, replayed: true, accessCredentialAvailable: false });
  fillPassengerForm();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Crear reserva" })); });
  expect(screen.getByRole("heading", { name: "Elige tu asiento" })).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("no podemos recuperar su credencial");
  expect(confirm).not.toHaveBeenCalled();
});

test("keeps the same idempotency key when confirmation is still pending", async () => {
  create.mockResolvedValue({
    ...pending, accessToken: "demo-capability", replayed: false, accessCredentialAvailable: true,
  });
  const unresolved = { ...pending, sequence: 2, bookingCode: null, failureReason: null };
  confirm.mockResolvedValue(unresolved);
  readReservation.mockResolvedValue(unresolved);
  fillPassengerForm();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Crear reserva" })); });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Confirmar reserva" }));
    await jest.advanceTimersByTimeAsync(4_500);
  });
  expect(confirm).toHaveBeenCalledTimes(5);
  expect(new Set(confirm.mock.calls.map(([, , key]) => key)).size).toBe(1);
  expect(screen.getByRole("status").textContent).toContain("La reserva sigue procesándose");
});
