import type { FlightSeat } from "@/shared/api/contracts";

export function summarizeOccupancy(seats: readonly FlightSeat[]) {
  const counts = { AVAILABLE: 0, HELD: 0, BOOKED: 0, UNAVAILABLE: 0 };
  for (const seat of seats) counts[seat.status]++;
  return { ...counts, capacity: seats.length - counts.UNAVAILABLE };
}
