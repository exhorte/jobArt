import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, errorMessage } from "@/lib/api";

function mockFetch(status: number, body: unknown, init: { raw?: boolean } = {}) {
  const text = body === undefined ? "" : init.raw ? String(body) : JSON.stringify(body);
  const fn = vi.fn().mockResolvedValue(new Response(status === 204 ? null : text, { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

/** Attend le rejet d'une requête et rend l'erreur typée (échoue si rien n'est levé). */
async function failure(request: Promise<unknown>): Promise<ApiError> {
  try {
    await request;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error("une erreur était attendue");
}

describe("client API", () => {
  it("renvoie le JSON d'une réponse réussie et passe par le proxy /api", async () => {
    const fetchMock = mockFetch(200, { status: "ok" });
    await expect(api.get<{ status: string }>("/health")).resolves.toEqual({ status: "ok" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/health");
  });

  it("envoie un corps JSON et l'en-tête Content-Type sur POST/PATCH", async () => {
    const fetchMock = mockFetch(200, {});
    await api.patch("/offers/1/status", { user_status: "saved" });
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe('{"user_status":"saved"}');
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("204 → undefined", async () => {
    mockFetch(204, undefined);
    await expect(api.delete("/search-profiles/3")).resolves.toBeUndefined();
  });

  it("détail texte FastAPI", async () => {
    mockFetch(404, { detail: "annonce introuvable" });
    await expect(api.get("/offers/9")).rejects.toMatchObject({ message: "annonce introuvable", status: 404 });
  });

  it("détail de validation Pydantic : champ + message lisible", async () => {
    mockFetch(422, { detail: [{ loc: ["body", "weights"], msg: "Value error, pondération(s) inconnue(s) : x" }, { loc: ["body", "name"], msg: "Field required" }] });
    const err = await failure(api.post("/search-profiles", {}));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("weights : pondération(s) inconnue(s) : x ; name : Field required");
    expect(err.status).toBe(422);
  });

  it("détail objet {message, active_run_id} conservé pour la logique appelante", async () => {
    mockFetch(409, { detail: { message: "une collecte est déjà en cours (exécution 7)", active_run_id: 7 } });
    const err = await failure(api.post("/search-runs", {}));
    expect(err.message).toBe("une collecte est déjà en cours (exécution 7)");
    expect(err.detail).toMatchObject({ active_run_id: 7 });
  });

  it("réponse d'erreur non JSON : message de repli avec le code HTTP", async () => {
    mockFetch(500, "<html>boom</html>", { raw: true });
    await expect(api.get("/dashboard")).rejects.toMatchObject({ status: 500 });
  });

  it("serveur injoignable : erreur lisible, statut 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const err = await failure(api.get("/health"));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.message).toMatch(/Impossible de joindre/);
  });

  it("errorMessage tolère les valeurs inattendues", () => {
    expect(errorMessage(new Error("x"))).toBe("x");
    expect(errorMessage("autre")).toBe("Erreur inattendue.");
  });
});
