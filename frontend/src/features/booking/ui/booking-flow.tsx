"use client";

import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { createPortal } from "react-dom";

import type { Flight } from "@/features/flight-search/model/types";
import {
  apiWebSocketBaseUrl,
  confirmReservation,
  createReservation,
  getReservation,
} from "@/shared/api/client";
import type {
  FlightSeat,
  ReservationEvent,
  ReservationStatus,
} from "@/shared/api/contracts";
import { observeFlightSeats } from "@/shared/api/observe-flight-seats";
import { newlyOccupiedSeats } from "@/shared/api/seat-availability";
import {
  bookingSteps,
  isPassengerDetailsValid,
  type BookingStep,
  type PassengerDetails,
} from "../model/booking";

type ActiveReservation = ReservationStatus & {
  accessToken: string;
  confirmKey: string;
};

const seatNumberPattern = /^(\d+)([A-Z]+)$/;

function formatPrice(amount: number, currency: string) {
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

function errorMessage(error: unknown) {
  const code = error instanceof Error ? error.message : "";
  const messages: Record<string, string> = {
    BACKEND_UNAVAILABLE:
      "No pudimos conectar con el servidor. Revisa tu conexión e inténtalo otra vez.",
    SEAT_UNAVAILABLE:
      "Alguien tomó este asiento antes. Actualizamos el mapa; elige otro.",
    FLIGHT_OR_SEAT_NOT_FOUND: "El vuelo o el asiento ya no está disponible.",
    IDEMPOTENCY_KEY_REUSED:
      "La solicitud ya se procesó con otra información. Inicia una nueva reserva.",
    RESERVATION_EXPIRED:
      "El tiempo para completar la reserva terminó. Elige el vuelo y asiento de nuevo.",
    RESERVATION_NOT_CONFIRMABLE:
      "Esta reserva ya no se puede confirmar. Consulta su estado o inicia otra.",
    RESERVATION_NOT_FOUND: "No encontramos la reserva.",
    UNAUTHORIZED: "La sesión de esta reserva ya no es válida. Inicia otra reserva.",
  };
  return messages[code] ?? "Ocurrió un problema al procesar la reserva. Inténtalo de nuevo.";
}

function newIdempotencyKey() {
  return crypto.randomUUID();
}

function groupSeats(seats: FlightSeat[]) {
  const rows = new Map<string, FlightSeat[]>();
  for (const seat of seats) {
    const rowNumber = seat.seatNumber.match(seatNumberPattern)?.[1] ?? "Otros";
    rows.set(rowNumber, [...(rows.get(rowNumber) ?? []), seat]);
  }
  return [...rows.entries()]
    .sort(([left], [right]) => {
      if (left === "Otros") return 1;
      if (right === "Otros") return -1;
      return Number(left) - Number(right);
    })
    .map(([number, rowSeats]) => [
      number,
      rowSeats.sort((left, right) => left.seatNumber.localeCompare(right.seatNumber)),
    ] as const);
}

function isTerminal(status: ReservationStatus["status"]) {
  return status === "CONFIRMED" || status === "FAILED" || status === "EXPIRED";
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function BookingFlow({
  flight,
  onCancel,
}: {
  flight: Flight;
  onCancel: () => void;
}) {
  const [step, setStep] = useState<BookingStep>(1);
  const [seats, setSeats] = useState<FlightSeat[]>([]);
  const [seatsLoading, setSeatsLoading] = useState(true);
  const [seat, setSeat] = useState("");
  const [passenger, setPassenger] = useState<PassengerDetails>({
    fullName: "",
    email: "",
  });
  const [reservation, setReservation] = useState<ActiveReservation | null>(null);
  const [formError, setFormError] = useState("");
  const [seatNotice, setSeatNotice] = useState("");
  const seatNoticeTimeoutRef = useRef<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const sequenceRef = useRef(1);
  const selectedSeatRef = useRef(seat);
  const stepRef = useRef(step);
  const busyRef = useRef(false);
  const refreshSeatsRef = useRef<(() => Promise<void>) | null>(null);
  const activeReservationId = reservation?.reservationId;
  const hasReservation = activeReservationId !== undefined;
  useEffect(() => {
    sequenceRef.current = reservation?.sequence ?? 1;
  }, [reservation?.sequence]);
  useEffect(() => {
    selectedSeatRef.current = seat;
    stepRef.current = step;
  }, [seat, step]);
  useEffect(
    () => () => {
      if (seatNoticeTimeoutRef.current !== null) {
        window.clearTimeout(seatNoticeTimeoutRef.current);
      }
    },
    [],
  );
  const seatRows = useMemo(() => groupSeats(seats), [seats]);
  const reservationPrice =
    reservation?.amount != null && reservation.currency
      ? formatPrice(reservation.amount, reservation.currency)
      : formatPrice(flight.price, flight.currency);

  function notifySeatUnavailable(message: string) {
    setSeatNotice(message);
    if (seatNoticeTimeoutRef.current !== null) {
      window.clearTimeout(seatNoticeTimeoutRef.current);
    }
    seatNoticeTimeoutRef.current = window.setTimeout(() => {
      setSeatNotice("");
      seatNoticeTimeoutRef.current = null;
    }, 7_000);
  }

  function dismissSeatNotice() {
    setSeatNotice("");
    if (seatNoticeTimeoutRef.current !== null) {
      window.clearTimeout(seatNoticeTimeoutRef.current);
      seatNoticeTimeoutRef.current = null;
    }
  }

  const seatSelectionActive = step === 1 || step === 2;
  useEffect(() => {
    if (!seatSelectionActive || hasReservation) return;
    const observer = observeFlightSeats(
      flight.id,
      (currentSeats, previousSeats) => {
        setSeats(currentSeats);
        setSeatsLoading(false);
        const selectedSeat = selectedSeatRef.current;
        const occupied = newlyOccupiedSeats(previousSeats, currentSeats)
          .filter((number) => !busyRef.current || number !== selectedSeat);
        const stillAvailable = currentSeats.some(
          (item) =>
            item.seatNumber === selectedSeat && item.status === "AVAILABLE",
        );
        if (selectedSeat && !stillAvailable && !busyRef.current) {
          selectedSeatRef.current = "";
          setSeat("");
          notifySeatUnavailable(
            `El asiento ${selectedSeat} ya no está disponible. Elige otro para continuar.`,
          );
          if (stepRef.current === 2) setStep(1);
        } else if (occupied.length === 1) {
          notifySeatUnavailable(`El asiento ${occupied[0]} ya no está disponible.`);
        } else if (occupied.length > 1) {
          notifySeatUnavailable(`Los asientos ${occupied.join(", ")} ya no están disponibles.`);
        }
      },
      (error) => {
        setFormError(errorMessage(error));
        setSeatsLoading(false);
      },
    );
    refreshSeatsRef.current = observer.refresh;
    return () => {
      refreshSeatsRef.current = null;
      observer.stop();
    };
  }, [flight.id, seatSelectionActive, hasReservation]);

  const reservationId = activeReservationId;
  const accessToken = reservation?.accessToken;
  const reservationStatus = reservation?.status;

  useEffect(() => {
    if (
      !reservationId ||
      !accessToken ||
      !reservationStatus ||
      isTerminal(reservationStatus)
    ) return;
    let active = true;
    let socket: WebSocket | undefined;

    try {
      socket = new WebSocket(
        `${apiWebSocketBaseUrl()}/reservations/${encodeURIComponent(reservationId)}/events/ws`,
      );
      socket.onopen = () => {
        socket?.send(
          JSON.stringify({
            type: "subscribe",
            accessToken,
            afterSequence: sequenceRef.current,
          }),
        );
      };
      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as ReservationEvent;
          if (
            event.type !== "reservation.updated" ||
            !Number.isInteger(event.sequence)
          ) {
            return;
          }
          setReservation((current) => {
            if (!current || event.sequence <= current.sequence) return current;
            return {
              ...current,
              sequence: event.sequence,
              status: event.status,
              bookingCode: event.bookingCode,
              failureReason: event.failureReason,
            };
          });
        } catch {
          // Ignore malformed WebSocket messages; HTTP remains the source of truth.
        }
      };
    } catch {
      // Browsers may not support WebSocket; the status polling below still works.
    }

    const interval = window.setInterval(async () => {
      try {
        const latest = await getReservation(
          reservationId,
          accessToken,
        );
        if (active) {
          setReservation((current) =>
            current && latest.sequence >= current.sequence
              ? { ...current, ...latest }
              : current,
          );
        }
      } catch {
        if (active) setStatusMessage("No pudimos actualizar el estado. Reintentaremos.");
      }
    }, 2_000);

    return () => {
      active = false;
      window.clearInterval(interval);
      socket?.close();
    };
  }, [reservationId, accessToken, reservationStatus]);

  async function submitPassenger(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isPassengerDetailsValid(passenger)) {
      setFormError("Escribe tu nombre completo y un correo válido.");
      return;
    }
    if (!seat) {
      setFormError("Selecciona un asiento disponible antes de continuar.");
      setStep(1);
      return;
    }

    setBusy(true);
    busyRef.current = true;
    setFormError("");
    setSeatNotice("");
    try {
      const result = await createReservation({
        flightId: flight.id,
        seatNumber: seat,
        passenger: {
          fullName: passenger.fullName.trim(),
          email: passenger.email.trim(),
        },
        idempotencyKey: newIdempotencyKey(),
      });
      if (result.replayed || !result.accessCredentialAvailable || !result.accessToken) {
        setFormError(
          "La reserva ya se había creado, pero por seguridad no podemos recuperar su credencial. Elige otro asiento o vuelve a intentarlo cuando venza el bloqueo.",
        );
        setStep(1);
        setSeat("");
        return;
      }
      setReservation({
        reservationId: result.reservationId,
        status: result.status,
        flightId: result.flightId,
        seatNumber: result.seatNumber,
        amount: result.amount,
        currency: result.currency,
        expiresAt: result.expiresAt,
        bookingCode: null,
        failureReason: null,
        sequence: 1,
        accessToken: result.accessToken,
        confirmKey: newIdempotencyKey(),
      });
      setStep(3);
    } catch (error) {
      if (error instanceof Error && error.message === "SEAT_UNAVAILABLE") {
        notifySeatUnavailable(
          `El asiento ${seat} acaba de ser tomado por otra persona. Elige otro para continuar.`,
        );
        selectedSeatRef.current = "";
        void refreshSeatsRef.current?.();
        setSeat("");
        setStep(1);
      } else {
        setFormError(errorMessage(error));
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  async function finishPurchase() {
    if (!reservation) return;
    setBusy(true);
    setFormError("");
    setStatusMessage("Estamos confirmando el asiento y el pago ficticio…");
    try {
      let latest: ReservationStatus | undefined;
      for (let attempt = 0; attempt < 5; attempt += 1) {
        latest = await confirmReservation(
          reservation.reservationId,
          reservation.accessToken,
          reservation.confirmKey,
        );
        setReservation((current) =>
          current && latest && latest.sequence >= current.sequence
            ? { ...current, ...latest }
            : current,
        );
        if (isTerminal(latest.status)) {
          setStep(4);
          setStatusMessage("");
          return;
        }
        await wait(900);
      }
      setStatusMessage(
        "La reserva sigue procesándose. Puedes volver a consultar; no inicies otra reserva.",
      );
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="booking-heading" className="booking-section" id="booking">
      {seatNotice && createPortal(
        <div aria-atomic="true" className="seat-toast" role="alert">
          <span aria-hidden="true" className="seat-toast-icon">!</span>
          <div className="seat-toast-content">
            <strong>Asiento ocupado</strong>
            <p>{seatNotice}</p>
          </div>
          <button
            aria-label="Cerrar notificación"
            className="seat-toast-close"
            onClick={dismissSeatNotice}
            type="button"
          >
            ×
          </button>
        </div>,
        document.body,
      )}
      <div className="booking-heading">
        <div>
          <p className="eyebrow">RESERVA DE VUELO</p>
          <h2 id="booking-heading">Completa tu viaje</h2>
        </div>
        {!reservation && (
          <button className="button button-secondary" onClick={onCancel} type="button">
            Volver a vuelos
          </button>
        )}
      </div>

      <ol aria-label="Progreso de reserva" className="booking-stepper">
        {bookingSteps.map((label, index) => {
          const stepIndex = index as BookingStep;
          const state =
            stepIndex === step ? "actual" : stepIndex < step ? "completado" : "pendiente";
          return (
            <li
              aria-current={stepIndex === step ? "step" : undefined}
              className={`step-${state}`}
              key={label}
            >
              <span aria-hidden="true" className="step-number">
                {stepIndex < step ? "✓" : index + 1}
              </span>
              <span className="step-label">{label}</span>
            </li>
          );
        })}
      </ol>

      <div className="booking-summary">
        <div>
          <span className="summary-label">Tu vuelo</span>
          <strong>{flight.origin.code} → {flight.destination.code}</strong>
          <span>{flight.airline} · {flight.flightNumber} · {flight.origin.time}–{flight.destination.time}</span>
        </div>
        <div>
          <span className="summary-label">Precio por persona</span>
          <strong>{reservationPrice}</strong>
        </div>
      </div>

      {step === 1 && (
        <div aria-labelledby="seats-heading" className="booking-panel">
          <div className="booking-panel-heading">
            <div>
              <p className="eyebrow">PASO 2 DE 5</p>
              <h3 id="seats-heading">Elige tu asiento</h3>
            </div>
          </div>
          {formError && <p className="form-error" role="alert">{formError}</p>}
          <div aria-label="Leyenda de asientos" className="seat-legend">
            <span><i aria-hidden="true" className="size-4 rounded border border-emerald-300 bg-emerald-50" /> Disponible</span>
            <span><i aria-hidden="true" className="size-4 rounded border border-teal-700 bg-teal-700" /> Seleccionado</span>
            <span><i aria-hidden="true" className="size-4 rounded border border-slate-300 bg-slate-200" /> No disponible</span>
          </div>
          {seatsLoading ? (
            <p role="status">Consultando asientos…</p>
          ) : seats.length === 0 ? (
            <p role="status">Este vuelo no tiene asientos para mostrar.</p>
          ) : (
            <div aria-label="Selección de asiento" className="seat-map">
              {seatRows.map(([rowNumber, rowSeats]) => (
                <div className="seat-row" key={rowNumber}>
                  <span aria-hidden="true" className="seat-row-number">{rowNumber}</span>
                  {rowSeats.map((item, index) => {
                    const selected = seat === item.seatNumber;
                    const unavailable = item.status !== "AVAILABLE";
                    const className = unavailable
                      ? "cursor-not-allowed border-slate-300 bg-slate-200 text-slate-600"
                      : selected
                        ? "border-teal-900! bg-teal-700! text-white outline outline-2 outline-teal-900"
                        : "border-emerald-300 bg-emerald-50 text-emerald-950 hover:border-emerald-600 hover:bg-emerald-100";
                    return (
                      <Fragment key={item.seatNumber}>
                        {index === 3 && <span aria-hidden="true" className="seat-aisle" />}
                        <span>
                          <button
                            aria-pressed={selected}
                            aria-label={`Asiento ${item.seatNumber}${unavailable ? `, ${item.status.toLowerCase()}` : selected ? ", seleccionado" : ", disponible"}`}
                            className={`seat min-h-9 w-full min-w-0 rounded-md border text-[10px] font-bold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:opacity-100 ${className}`}
                            disabled={unavailable || busy}
                            onClick={() => {
                              setSeat(item.seatNumber);
                              dismissSeatNotice();
                              setFormError("");
                            }}
                            type="button"
                          >
                            {item.seatNumber}
                          </button>
                        </span>
                      </Fragment>
                    );
                  })}
                </div>
              ))}
            </div>
          )}
          <p aria-live="polite" className="seat-selection-message">
            {seat ? `Asiento ${seat} seleccionado.` : "Aún no has seleccionado un asiento."}
          </p>
          <div className="booking-actions">
            <button
              className="button button-primary"
              disabled={!seat || seatsLoading || busy}
              onClick={() => {
                setFormError("");
                dismissSeatNotice();
                setStep(2);
              }}
              type="button"
            >
              Continuar con {seat ? `asiento ${seat}` : "el pasajero"}
            </button>
          </div>
        </div>
      )}

      {step === 2 && (
        <form className="booking-panel passenger-form" onSubmit={submitPassenger}>
          <p className="eyebrow">PASO 3 DE 5</p>
          <h3>Pasajero y facturación</h3>
          <label className="form-field">
            <span>Nombre completo</span>
            <input
              autoComplete="name"
              minLength={2}
              onChange={(event) => setPassenger({ ...passenger, fullName: event.target.value })}
              required
              value={passenger.fullName}
            />
          </label>
          <label className="form-field">
            <span>Correo electrónico</span>
            <input
              autoComplete="email"
              onChange={(event) => setPassenger({ ...passenger, email: event.target.value })}
              required
              type="email"
              value={passenger.email}
            />
          </label>
          {formError && <p className="form-error" role="alert">{formError}</p>}
          <div className="booking-actions">
            <button className="button button-secondary" disabled={busy} onClick={() => setStep(1)} type="button">Volver a asientos</button>
            <button className="button button-primary" disabled={busy} type="submit">
              {busy ? "Bloqueando asiento…" : "Crear reserva"}
            </button>
          </div>
        </form>
      )}

      {step === 3 && reservation && (
        <div className="booking-panel">
          <p className="eyebrow">PASO 4 DE 5</p>
          <h3>Revisa tu reserva</h3>
          <dl className="review-details">
            <div><dt>Pasajero</dt><dd>{passenger.fullName}</dd></div>
            <div><dt>Correo</dt><dd>{passenger.email}</dd></div>
            <div><dt>Asiento bloqueado</dt><dd>{reservation.seatNumber}</dd></div>
            <div><dt>Vuelo</dt><dd>{flight.flightNumber} · {flight.origin.code} → {flight.destination.code}</dd></div>
            <div><dt>Total</dt><dd>{reservationPrice}</dd></div>
            <div><dt>Vence</dt><dd><time dateTime={reservation.expiresAt}>{new Date(reservation.expiresAt).toLocaleString("es-CO")}</time></dd></div>
          </dl>
          <p className="demo-notice" role="note">El pago es ficticio. No se procesan cobros ni se solicitan datos de tarjeta.</p>
          {formError && <p className="form-error" role="alert">{formError}</p>}
          {statusMessage && <p aria-live="polite" role="status">{statusMessage}</p>}
          <div className="booking-actions">
            <button className="button button-primary" disabled={busy} onClick={finishPurchase} type="button">
              {busy ? "Procesando…" : reservation.status === "PENDING" ? "Confirmar reserva" : "Consultar estado"}
            </button>
          </div>
        </div>
      )}

      {step === 4 && reservation && (
        <div className={`booking-panel ${reservation.status === "CONFIRMED" ? "booking-success" : ""}`} role="status">
          {reservation.status === "CONFIRMED" ? (
            <>
              <span aria-hidden="true" className="success-mark">✓</span>
              <p className="eyebrow">PASO 5 DE 5</p>
              <h3>¡Reserva confirmada!</h3>
              <p>Hola, {passenger.fullName}. Tu vuelo {flight.flightNumber}, asiento {reservation.seatNumber}, está confirmado.</p>
              <p>Código de reserva: <strong>{reservation.bookingCode}</strong></p>
              <p>Enviaremos la información a <strong>{passenger.email}</strong>.</p>
            </>
          ) : (
            <>
              <p className="eyebrow">RESERVA FINALIZADA</p>
              <h3>{reservation.status === "EXPIRED" ? "El tiempo de reserva venció" : "No se pudo confirmar la reserva"}</h3>
              <p>{reservation.failureReason ?? "El asiento fue liberado. Vuelve a buscar disponibilidad para intentarlo otra vez."}</p>
            </>
          )}
          <button className="button button-primary" onClick={onCancel} type="button">Volver a resultados</button>
        </div>
      )}
    </section>
  );
}
