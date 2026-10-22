/** Client HTTP du backend (via le proxy same-origin `/api`) et hook de lecture avec rafraîchissement automatique. */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Rend lisible le `detail` d'une erreur FastAPI (texte, objet {message} ou liste de validation Pydantic). */
function describeDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d) => {
      const loc = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
      const msg = String(d?.msg ?? "valeur invalide").replace(/^Value error, /, "");
      return loc ? `${loc} : ${msg}` : msg;
    });
    return parts.join(" ; ") || fallback;
  }
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      signal,
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError("Impossible de joindre le serveur de l'application.", 0);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(describeDetail(detail, `Erreur ${res.status}`), res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  delete: <T = void>(path: string) => request<T>("DELETE", path),
};

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : "Erreur inattendue.";
}

export interface UseApiOptions {
  /** Rafraîchissement périodique en ms : nombre fixe, `false` (aucun) ou fonction des dernières données (cadence adaptative). */
  refreshMs?: number | false | ((data: unknown) => number | false);
}

export interface ApiState<T> {
  data: T | undefined;
  error: string | null;
  /** Vrai tant qu'aucune réponse (ni erreur) n'a été reçue ; les données précédentes restent affichées pendant un rechargement. */
  loading: boolean;
  /** Vrai pendant toute requête en cours (y compris un rechargement avec données précédentes affichées). */
  fetching: boolean;
  reload: () => Promise<void>;
  setData: (updater: (prev: T | undefined) => T | undefined) => void;
}

/**
 * Lecture GET avec état de chargement/erreur. `path = null` suspend la requête. Une erreur de rafraîchissement
 * n'efface pas les dernières données valides (elles restent affichées avec le message d'erreur).
 */
export function useApi<T>(path: string | null, options: UseApiOptions = {}): ApiState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const optionsRef = useRef(options);
  const dataRef = useRef<T | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    optionsRef.current = options;
  });

  const fetchOnce = useCallback(async (): Promise<void> => {
    if (path === null) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setFetching(true);
    try {
      const result = await api.get<T>(path, ctrl.signal);
      if (ctrl.signal.aborted) return;
      dataRef.current = result;
      setDataState(result);
      setError(null);
    } catch (e) {
      if (ctrl.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
      setError(errorMessage(e));
    } finally {
      if (!ctrl.signal.aborted) setFetching(false);
    }
  }, [path]);

  useEffect(() => {
    if (path === null) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const loop = async () => {
      await fetchOnce();
      if (stopped) return;
      const r = optionsRef.current.refreshMs;
      const every = typeof r === "function" ? r(dataRef.current) : r;
      if (every) timer = setTimeout(loop, every);
    };
    void loop();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [path, fetchOnce]);

  const setData = useCallback((updater: (prev: T | undefined) => T | undefined) => {
    setDataState((prev) => {
      const next = updater(prev);
      dataRef.current = next;
      return next;
    });
  }, []);

  return { data, error, loading: path !== null && data === undefined && error === null, fetching, reload: fetchOnce, setData };
}
