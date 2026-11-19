import { airports } from "../data/demo-flights.ts";

type FlightSearchFormProps = {
  origin: string;
  destination: string;
  departureDate: string;
  action?: string;
};

export function FlightSearchForm({
  origin,
  destination,
  departureDate,
  action = "/",
}: FlightSearchFormProps) {
  return (
    <form action={action} className="search-form" method="get">
      <div className="form-field">
        <label htmlFor="origin">Desde</label>
        <select defaultValue={origin} id="origin" name="origin" required>
          <option disabled value="">
            Selecciona un aeropuerto
          </option>
          {airports.map((airport) => (
            <option key={airport.code} value={airport.code}>
              {airport.city} ({airport.code})
            </option>
          ))}
        </select>
      </div>

      <div aria-hidden="true" className="route-swap">
        ⇄
      </div>

      <div className="form-field">
        <label htmlFor="destination">Hacia</label>
        <select
          defaultValue={destination}
          id="destination"
          name="destination"
          required
        >
          <option disabled value="">
            Selecciona un aeropuerto
          </option>
          {airports.map((airport) => (
            <option key={airport.code} value={airport.code}>
              {airport.city} ({airport.code})
            </option>
          ))}
        </select>
      </div>

      <div className="form-field date-field">
        <label htmlFor="departureDate">Fecha de salida</label>
        <input
          defaultValue={departureDate}
          id="departureDate"
          name="departureDate"
          required
          type="date"
        />
      </div>

      <button className="button button-primary search-submit" type="submit">
        <span aria-hidden="true">⌕</span>
        Buscar vuelos
      </button>
    </form>
  );
}
