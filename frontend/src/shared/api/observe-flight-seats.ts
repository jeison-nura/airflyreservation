import { apiWebSocketBaseUrl, getFlightSeats } from "./client";
import type { FlightSeat } from "./contracts";
import { parseSeatUpdate } from "./seat-availability";

export function observeFlightSeats(
  flightId: string,
  onSeats: (current: FlightSeat[], previous: FlightSeat[]) => void,
  onError: (error: unknown) => void,
) {
  let active = true;
  let loading = false;
  let needsRefresh = true;
  let revision = 0;
  let current: FlightSeat[] = [];
  let socket: WebSocket | undefined;

  function publish(next: FlightSeat[]) {
    const previous = current;
    current = next;
    onSeats(next, previous);
  }

  async function refresh() {
    if (!active || loading) return;
    loading = true;
    const startedAtRevision = revision;
    try {
      const seats = await getFlightSeats(flightId);
      if (active && revision === startedAtRevision) {
        needsRefresh = false;
        publish(seats);
      }
    } catch (error) {
      needsRefresh = true;
      if (active) onError(error);
    } finally {
      loading = false;
      // A response started before a frame may contain an older view of that seat.
      if (active && revision !== startedAtRevision) void refresh();
    }
  }

  function connect() {
    if (!active || (socket && socket.readyState !== WebSocket.CLOSED)) return;
    try {
      socket = new WebSocket(
        `${apiWebSocketBaseUrl()}/inventory/flights/${encodeURIComponent(flightId)}/events/ws`,
      );
      socket.onopen = socket.onclose = () => {
        // Reconcile any changes between the initial fetch and subscription, or during a drop.
        revision++;
        void refresh();
      };
      socket.onmessage = ({ data }) => {
        if (!active) return;
        const event = parseSeatUpdate(data, flightId);
        if (!event) return;
        revision++;
        const before = current.find((seat) => seat.seatNumber === event.seatNumber);
        if (!before) {
          void refresh();
        } else if (before.status !== event.status) {
          publish(current.map((seat) => seat === before ? event : seat));
        }
      };
    } catch {
      // HTTP remains available if the browser cannot open a socket.
    }
  }

  void refresh();
  // Avoid opening a connection for React's synchronous setup/cleanup probe in development.
  const initialConnection = window.setTimeout(connect, 0);
  const fallback = window.setInterval(() => {
    if (needsRefresh || socket?.readyState !== WebSocket.OPEN) void refresh();
    connect();
  }, 3_000);

  return {
    refresh,
    stop() {
      active = false;
      window.clearTimeout(initialConnection);
      window.clearInterval(fallback);
      socket?.close();
    },
  };
}
