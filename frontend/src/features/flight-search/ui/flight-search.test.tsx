/** @jest-environment jsdom */

import { afterEach, beforeAll, expect, jest, test } from "@jest/globals";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { demoFlights } from "../data/demo-flights";
import { FlightSearchForm } from "./flight-search-form";

let FlightResults: typeof import("./flight-results").FlightResults;

beforeAll(async () => {
  jest.doMock("@/shared/api/observe-flight-seats", () => ({
    observeFlightSeats: () => ({ refresh: async () => {}, stop: () => {} }),
  }));
  ({ FlightResults } = await import("./flight-results"));
});

afterEach(() => cleanup());

const criteria = { origin: "BOG", destination: "MDE", departureDate: "2026-11-19" };

test("uses the search fields as GET parameters and supports the statistics route", () => {
  const { rerender } = render(<FlightSearchForm {...criteria} />);
  const submit = screen.getByRole<HTMLButtonElement>("button", { name: "Buscar vuelos" });
  const form = submit.form!;
  expect(form.method).toBe("get");
  expect(form.getAttribute("action")).toBe("/");
  expect(Object.fromEntries(new FormData(form))).toEqual(criteria);
  fireEvent.change(screen.getByRole("combobox", { name: "Hacia" }), { target: { value: "CLO" } });
  expect(new FormData(form).get("destination")).toBe("CLO");

  rerender(<FlightSearchForm {...criteria} action="/estadisticas" />);
  expect(submit.form?.getAttribute("action")).toBe("/estadisticas");
});

test("lists availability and flight status, then opens and closes the chosen booking", () => {
  const flights = [demoFlights[0], demoFlights[2], { ...demoFlights[3], status: "CANCELLED" as const }];
  render(<FlightResults {...criteria} flights={flights} />);
  expect(screen.getByText("3 opciones")).toBeTruthy();
  expect(screen.getByText("Con demora")).toBeTruthy();
  expect(screen.getByText("Cancelado")).toBeTruthy();

  const flight = screen.getByRole("article", { name: /AA 204/ });
  expect(within(flight).getByText("18 asientos disponibles")).toBeTruthy();
  expect(within(flight).getByText("07:10")).toBeTruthy();
  fireEvent.click(within(flight).getByRole("button", { name: "Elegir vuelo" }));
  expect(screen.getByRole("heading", { name: "Completa tu viaje" })).toBeTruthy();
  expect(screen.getByText(/AA 204 · 07:10/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Volver a vuelos" }));
  expect(screen.getByRole("heading", { name: "Vuelos disponibles" })).toBeTruthy();
});

test("distinguishes no flights from an unavailable search", () => {
  const props = { ...criteria, departureDate: "fecha sin formato", flights: [] };
  const { rerender } = render(<FlightResults {...props} />);
  expect(screen.getByRole("status").textContent).toContain("No encontramos vuelos");
  expect(screen.getByText("fecha sin formato")).toBeTruthy();

  rerender(<FlightResults {...props} searchError="No se pudo consultar Inventory" />);
  expect(screen.getByRole("alert").textContent).toBe("No se pudo consultar Inventory");
  expect(screen.queryByText("No encontramos vuelos para esta búsqueda")).toBeNull();
});
