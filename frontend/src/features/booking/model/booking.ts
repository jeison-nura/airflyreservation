export const bookingSteps = [
  "Vuelo",
  "Asientos",
  "Pasajero y facturación",
  "Revisión y pago",
  "Confirmación",
] as const;

export type BookingStep = 0 | 1 | 2 | 3 | 4;

export type PassengerDetails = {
  fullName: string;
  email: string;
};

export function isPassengerDetailsValid(details: PassengerDetails) {
  return (
    details.fullName.trim().length >= 2 &&
    /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(details.email.trim())
  );
}

export function canGoToStep(target: BookingStep, current: BookingStep) {
  return target <= current;
}
