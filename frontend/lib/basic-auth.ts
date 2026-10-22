import { createHash, timingSafeEqual } from "node:crypto";

/**
 * Protection d'accès par mot de passe (HTTP Basic) du site public.
 *
 * L'API FastAPI n'a aucune authentification : tout ce qui atteint le proxy `/api/*` doit donc d'abord passer ici.
 * - `BASIC_AUTH_USER` + `BASIC_AUTH_PASSWORD` définis → toute requête doit les présenter.
 * - Ni l'un ni l'autre, en local ou en Docker → accès libre (le port n'est publié que sur 127.0.0.1).
 * - Ni l'un ni l'autre, sur Vercel ou avec `REQUIRE_AUTH=1` → accès refusé (jamais ouvert par oubli de configuration).
 */

export const AUTH_REALM = "jobArt";

export type Env = Record<string, string | undefined>;
export type Credentials = { user: string; password: string };
export type AccessDecision = "allow" | "challenge" | "misconfigured";

/** Identifiants attendus, lus à chaque requête ; `null` si la protection n'est pas configurée. */
export function expectedCredentials(env: Env): Credentials | null {
  const user = env.BASIC_AUTH_USER?.trim();
  const password = env.BASIC_AUTH_PASSWORD;
  return user && password ? { user, password } : null;
}

/** Décode `Authorization: Basic base64(utilisateur:mot de passe)` ; `null` si absent ou illisible. */
export function parseBasicAuth(header: string | null | undefined): Credentials | null {
  const match = /^Basic\s+([A-Za-z0-9+/]+={0,2})\s*$/i.exec(header ?? "");
  if (!match) return null;
  const decoded = Buffer.from(match[1], "base64").toString("utf8");
  const separator = decoded.indexOf(":");
  if (separator < 0) return null;
  return { user: decoded.slice(0, separator), password: decoded.slice(separator + 1) };
}

/** Comparaison à temps constant : les deux valeurs sont d'abord ramenées à 32 octets par SHA-256. */
function sameSecret(given: string, expected: string): boolean {
  const hash = (value: string) => createHash("sha256").update(value).digest();
  return timingSafeEqual(hash(given), hash(expected));
}

export function isAuthorized(header: string | null | undefined, expected: Credentials): boolean {
  const given = parseBasicAuth(header);
  if (!given) return false;
  // Les deux comparaisons sont toujours évaluées : le temps de réponse ne révèle pas quel champ est faux.
  const userOk = sameSecret(given.user, expected.user);
  const passwordOk = sameSecret(given.password, expected.password);
  return userOk && passwordOk;
}

export function decideAccess(header: string | null | undefined, env: Env): AccessDecision {
  const expected = expectedCredentials(env);
  if (!expected) return env.VERCEL || env.REQUIRE_AUTH === "1" ? "misconfigured" : "allow";
  return isAuthorized(header, expected) ? "allow" : "challenge";
}
