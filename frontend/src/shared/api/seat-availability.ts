import type { FlightSeat } from "./contracts";

export function newlyOccupiedSeats(
  previous: readonly FlightSeat[],
  current: readonly FlightSeat[],
): string[] {
  const available = new Set(
    previous.filter((seat) => seat.status === "AVAILABLE").map((seat) => seat.seatNumber),
  );
  return current
    .filter((seat) => available.has(seat.seatNumber) && (
      seat.status === "HELD" || seat.status === "BOOKED"
    ))
    .map((seat) => seat.seatNumber);
}

export function parseSeatUpdate(data: unknown, flightId: string): FlightSeat | null {
  if (typeof data !== "string") return null;
  try {
    const event = JSON.parse(data);
    if (event?.type !== "seat.updated" || event.flightId !== flightId ||
        typeof event.seatNumber !== "string") return null;
    const { seatNumber, status } = event;
    if (status !== "AVAILABLE" && status !== "HELD" &&
        status !== "BOOKED" && status !== "UNAVAILABLE") return null;
    return { seatNumber, status };
  } catch {
    return null;
  }
}
