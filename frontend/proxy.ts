import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { AUTH_REALM, decideAccess } from "@/lib/basic-auth";

/**
 * Verrou d'accès du site public (voir `lib/basic-auth.ts`).
 *
 * Sans `matcher`, il couvre toutes les requêtes, y compris `/api/*` (proxy vers un backend sans authentification)
 * et les fichiers statiques : après la première saisie, le navigateur renvoie lui-même les identifiants.
 */
export function proxy(req: NextRequest) {
  const decision = decideAccess(req.headers.get("authorization"), process.env);
  if (decision === "allow") return NextResponse.next();

  if (decision === "misconfigured") {
    return new Response("Accès verrouillé : BASIC_AUTH_USER et BASIC_AUTH_PASSWORD ne sont pas définis.", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  return new Response("Authentification requise.", {
    status: 401,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
      "WWW-Authenticate": `Basic realm="${AUTH_REALM}", charset="UTF-8"`,
    },
  });
}
