const backendBaseUrl = (
  process.env.BACKEND_API_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

function isAllowedRequest(method: string, segments: string[]): boolean {
  if (method === "GET") {
    return (
      (segments.length === 2 && segments[0] === "inventory" && segments[1] === "flights") ||
      (segments.length === 4 &&
        segments[0] === "inventory" &&
        segments[1] === "flights" &&
        segments[3] === "seats") ||
      (segments.length === 3 &&
        segments[0] === "reservations" &&
        segments[2] === "events") ||
      (segments.length === 2 && segments[0] === "reservations")
    );
  }
  return (
    method === "POST" &&
    (segments.length === 1 && segments[0] === "reservations" ||
      segments.length === 3 &&
        segments[0] === "reservations" &&
        segments[2] === "confirm")
  );
}

type ProxyContext = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: ProxyContext) {
  return proxy(request, context, "GET");
}

export async function POST(request: Request, context: ProxyContext) {
  return proxy(request, context, "POST");
}

async function proxy(
  request: Request,
  context: ProxyContext,
  method: "GET" | "POST",
) {
  const { path } = await context.params;
  if (!isAllowedRequest(method, path)) {
    return Response.json({ detail: "NOT_FOUND" }, { status: 404 });
  }
  const incomingUrl = new URL(request.url);
  const target = `${backendBaseUrl}/${path.map(encodeURIComponent).join("/")}${incomingUrl.search}`;
  const headers = new Headers();
  for (const name of ["accept", "authorization", "content-type", "idempotency-key"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const upstream = await fetch(target, {
      method,
      headers,
      body: method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const responseHeaders = new Headers();
    const contentType = upstream.headers.get("content-type");
    if (contentType) responseHeaders.set("content-type", contentType);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      { detail: "BACKEND_UNAVAILABLE" },
      { status: 503 },
    );
  }
}
