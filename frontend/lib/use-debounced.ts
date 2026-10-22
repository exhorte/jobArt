"use client";

import { useEffect, useState } from "react";

/** Valeur retardée : évite une requête à chaque frappe dans un champ de filtre. */
export function useDebounced<T>(value: T, delayMs = 350): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(t);
  }, [value, delayMs]);
  return debounced;
}
