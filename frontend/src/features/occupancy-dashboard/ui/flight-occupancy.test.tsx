/** @jest-environment jsdom */

import { afterEach, beforeAll, expect, jest, test } from "@jest/globals";
import { act, cleanup, render, screen } from "@testing-library/react";
import { demoFlights } from "@/features/flight-search/data/demo-flights";
import type { observeFlightSeats } from "@/shared/api/observe-flight-seats";

const stop = jest.fn();
const observe = jest.fn<typeof observeFlightSeats>().mockReturnValue({
  refresh: async () => {},
  stop,
});
let FlightOccupancy: typeof import("./flight-occupancy").FlightOccupancy;

beforeAll(async () => {
  jest.doMock("@/shared/api/observe-flight-seats", () => ({ observeFlightSeats: observe }));
  ({ FlightOccupancy } = await import("./flight-occupancy"));
});

afterEach(() => cleanup());

test("renders live counts and retains the last known snapshot after a connection error", () => {
  const { unmount } = render(<FlightOccupancy flight={demoFlights[0]} />);
  expect(screen.getByRole("status").textContent).toContain("Consultando");
  const [, update, onError] = observe.mock.calls[0];

  act(() => update([
    { seatNumber: "1A", status: "AVAILABLE" },
    { seatNumber: "1B", status: "BOOKED" },
    { seatNumber: "1C", status: "UNAVAILABLE" },
  ], []));
  expect(screen.getByRole("meter", { name: "Ocupación confirmada: 50%" })).toBeTruthy();
  expect(screen.getByText("Fuera de servicio: 1")).toBeTruthy();

  act(() => onError(new Error("offline")));
  expect(screen.getByRole("status").textContent).toContain("últimos datos recibidos");
  expect(screen.getByRole("meter", { name: "Ocupación confirmada: 50%" })).toBeTruthy();

  act(() => update([{ seatNumber: "1C", status: "UNAVAILABLE" }], []));
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByText("No hay plazas habilitadas para este vuelo.")).toBeTruthy();
  unmount();
  expect(stop).toHaveBeenCalledTimes(1);
});
