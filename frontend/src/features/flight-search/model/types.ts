export type Airport = {
  code: string;
  city: string;
};

export type FlightStatus = "ON_TIME" | "DELAYED" | "CANCELLED";

export type Flight = {
  id: string;
  airline: string;
  flightNumber: string;
  origin: Airport & { time: string };
  destination: Airport & { time: string };
  departureDate: string;
  duration: string;
  price: number;
  currency: string;
  availableSeats: number;
  status: FlightStatus;
};

export type FlightSearchCriteria = {
  origin: string;
  destination: string;
  departureDate: string;
};
