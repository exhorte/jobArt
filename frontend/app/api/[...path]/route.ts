import type { NextRequest } from "next/server";

/**
 * Proxy `/api/*` → backend FastAPI.
 *
 * - `BACKEND_URL` est lu à chaque requête (une même image Docker sert tous les environnements).
 * - Seul le préfixe `/api/` du backend est joignable : le client ne peut pas choisir une autre URL de destination.
 * - Les corps et les en-têtes utiles sont transmis tels quels ; les erreurs réseau deviennent un 502 lisible.
 */
const BACKEND_URL = () => (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type"];
const DROPPED_RESPONSE_HEADERS = new Set(["content-encoding", "content-length", "transfer-encoding", "connection"]);

async function proxy(req: NextRequest, ctx: RouteContext<"/api/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${BACKEND_URL()}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);

  try {
    const upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
    const out = new Headers();
    upstream.headers.forEach((value, key) => {
      if (!DROPPED_RESPONSE_HEADERS.has(key.toLowerCase())) out.set(key, value);
    });
    return new Response(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: out });
  } catch {
    return Response.json(
      { detail: "Le backend jobArt est injoignable. Vérifiez qu'il est démarré (voir le README)." },
      { status: 502 },
    );
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE };
