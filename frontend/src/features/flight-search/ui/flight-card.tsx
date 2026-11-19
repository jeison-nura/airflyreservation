import type { Flight } from "../model/types.ts";

const currencyFormatters = new Map<string, Intl.NumberFormat>();

function formatPrice(amount: number, currency: string) {
  let formatter = currencyFormatters.get(currency);

  if (!formatter) {
    formatter = new Intl.NumberFormat("es-CO", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    });
    currencyFormatters.set(currency, formatter);
  }

  return formatter.format(amount);
}

function getStatusLabel(status: Flight["status"]) {
  if (status === "DELAYED") return "Con demora";
  if (status === "CANCELLED") return "Cancelado";
  return "A tiempo";
}

type FlightCardProps = {
  flight: Flight;
  onSelect: (flight: Flight) => void;
};

export function FlightCard({ flight, onSelect }: FlightCardProps) {
  return (
    <article aria-label={`${flight.airline}, vuelo ${flight.flightNumber}`} className="flight-card">
      <div className="flight-card-top">
        <div className="airline-mark" aria-hidden="true">
          A
        </div>
        <div>
          <p className="airline-name">{flight.airline}</p>
          <p className="flight-number">Vuelo {flight.flightNumber}</p>
        </div>
        <span className={`flight-status status-${flight.status.toLowerCase()}`}>
          <span aria-hidden="true" className="status-dot" />
          {getStatusLabel(flight.status)}
        </span>
      </div>

      <div className="flight-card-main">
        <div className="airport-time">
          <time className="time-value">{flight.origin.time}</time>
          <span className="airport-code">{flight.origin.code}</span>
          <span className="airport-city">{flight.origin.city}</span>
        </div>

        <div aria-label={`Duración del vuelo: ${flight.duration}`} className="flight-route">
          <span>{flight.duration}</span>
          <div aria-hidden="true" className="route-line">
            <span className="route-line-dot" />
            <span className="route-plane">✈</span>
            <span className="route-line-dot" />
          </div>
          <span>Directo</span>
        </div>

        <div className="airport-time airport-arrival">
          <time className="time-value">{flight.destination.time}</time>
          <span className="airport-code">{flight.destination.code}</span>
          <span className="airport-city">{flight.destination.city}</span>
        </div>
      </div>

      <div className="flight-card-bottom">
        <p className="availability">
          <span aria-hidden="true" className="availability-icon">◷</span>
          {flight.availableSeats} asientos disponibles
        </p>
        <div className="price-block">
          <span className="price-caption">Precio por persona</span>
          <strong className="flight-price">{formatPrice(flight.price, flight.currency)}</strong>
        </div>
        <button
          className="button button-primary select-flight-button"
          onClick={() => onSelect(flight)}
          type="button"
        >
          Elegir vuelo
        </button>
      </div>
    </article>
  );
}
