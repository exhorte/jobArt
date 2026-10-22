"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import { useToast } from "@/components/toast";
import { ApiError, api, errorMessage } from "@/lib/api";

/**
 * Lance une collecte (toutes les sources activées, ou `sourceKeys`/`profileId`) et ouvre son suivi dans l'historique.
 * La collecte est asynchrone côté backend : la requête rend l'identifiant d'exécution immédiatement.
 */
export function useLaunchRun() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const launch = useCallback(
    async (body: { source_keys?: string[]; profile_id?: number } = {}) => {
      setBusy(true);
      try {
        const { id } = await api.post<{ id: number }>("/search-runs", body);
        toast.success(`Collecte n° ${id} lancée : le suivi s'affiche dans l'historique.`);
        router.push(`/runs?run=${id}`);
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === "object" && "active_run_id" in e.detail) {
          const id = (e.detail as { active_run_id: number }).active_run_id;
          toast.info(`Une collecte est déjà en cours (n° ${id}).`);
          router.push(`/runs?run=${id}`);
        } else {
          toast.error(errorMessage(e));
        }
      } finally {
        setBusy(false);
      }
    },
    [router, toast],
  );

  return { launch, busy };
}
