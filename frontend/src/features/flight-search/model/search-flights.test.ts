import { expect, test } from "@jest/globals";

import { searchFlights } from "./search-flights";
import type { Flight } from "./types";

const flights: Flight[] = [
  {
    id: "flight-1",
    airline: "Aerolínea Andina",
    flightNumber: "AA 204",
    origin: { code: "BOG", city: "Bogotá", time: "07:10" },
    destination: { code: "MDE", city: "Medellín", time: "08:05" },
    departureDate: "2026-11-19",
    duration: "55 min",
    price: 189_900,
    currency: "COP",
    availableSeats: 18,
    status: "ON_TIME",
  },
  {
    id: "flight-2",
    airline: "Aerolínea Andina",
    flightNumber: "AA 318",
    origin: { code: "BOG", city: "Bogotá", time: "11:40" },
    destination: { code: "CLO", city: "Cali", time: "12:35" },
    departureDate: "2026-11-19",
    duration: "55 min",
    price: 164_500,
    currency: "COP",
    availableSeats: 6,
    status: "ON_TIME",
  },
  {
    id: "flight-3",
    airline: "Aerolínea Andina",
    flightNumber: "AA 522",
    origin: { code: "BOG", city: "Bogotá", time: "15:20" },
    destination: { code: "MDE", city: "Medellín", time: "16:15" },
    departureDate: "2026-11-20",
    duration: "55 min",
    price: 209_900,
    currency: "COP",
    availableSeats: 12,
    status: "ON_TIME",
  },
  {
    id: "flight-cancelled",
    airline: "Aerolínea Andina",
    flightNumber: "AA 700",
    origin: { code: "BOG", city: "Bogotá", time: "18:00" },
    destination: { code: "MDE", city: "Medellín", time: "18:55" },
    departureDate: "2026-11-19",
    duration: "55 min",
    price: 189_900,
    currency: "COP",
    availableSeats: 20,
    status: "CANCELLED",
  },
  {
    id: "flight-full",
    airline: "Aerolínea Andina",
    flightNumber: "AA 701",
    origin: { code: "BOG", city: "Bogotá", time: "19:00" },
    destination: { code: "MDE", city: "Medellín", time: "19:55" },
    departureDate: "2026-11-19",
    duration: "55 min",
    price: 189_900,
    currency: "COP",
    availableSeats: 0,
    status: "ON_TIME",
  },
];

test("searchFlights filters by origin, destination, and departure date", () => {
  const results = searchFlights(flights, {
    origin: " bog ",
    destination: "mde",
    departureDate: "2026-11-19",
  });

  expect(results.map((flight) => flight.id)).toEqual(["flight-1"]);
});

test("searchFlights excludes cancelled and fully booked flights", () => {
  const results = searchFlights(flights, {
    origin: "BOG",
    destination: "MDE",
    departureDate: "2026-11-19",
  });

  expect(results.some((flight) => flight.status === "CANCELLED" || flight.availableSeats === 0))
    .toBe(false);
});

test("searchFlights returns no flights when no route/date matches", () => {
  const results = searchFlights(flights, {
    origin: "MDE",
    destination: "BOG",
    departureDate: "2026-11-19",
  });

  expect(results).toEqual([]);
});

test("searchFlights does not mutate the source collection", () => {
  const source = [...flights];

  searchFlights(source, {
    origin: "BOG",
    destination: "MDE",
    departureDate: "2026-11-19",
  });

  expect(source).toEqual(flights);
});
