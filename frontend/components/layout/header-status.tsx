"use client";

import { Radar } from "lucide-react";

import { LaunchRunButton } from "@/components/launch-run-button";
import { StatusPill, type StatusTone } from "@/components/status-badge";
import { useApi } from "@/lib/api";
import { SCHEDULER_STATE_LABELS } from "@/lib/format";
import type { Health } from "@/lib/types";

const TONE: Record<Health["scheduler"]["state"], StatusTone> = { running: "success", stopped: "warning", disabled: "neutral" };

/** État RÉEL de la veille (battement de cœur du processus qui la porte), rafraîchi toutes les 30 s. */
export function HeaderStatus() {
  const { data, error } = useApi<Health>("/health", { refreshMs: 30_000 });

  if (error && !data) {
    return <StatusPill tone="destructive" label="Serveur injoignable" className="max-w-full" />;
  }
  if (!data) return <span className="inline-block h-9 w-40 animate-pulse rounded-md bg-muted/60" aria-hidden="true" />;
  const s = data.scheduler;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Radar className="hidden size-4 shrink-0 text-muted-foreground sm:block" aria-hidden="true" />
      <StatusPill
        tone={data.status === "ok" ? TONE[s.state] : "destructive"}
        label={data.status === "ok" ? `Veille : ${SCHEDULER_STATE_LABELS[s.state].toLowerCase()}` : "Base de données indisponible"}
        className="min-w-0 max-w-full truncate"
      />
    </div>
  );
}

/** Action principale de la barre supérieure : lance une collecte (asynchrone, suivi dans l'historique). */
export function HeaderActions() {
  return <LaunchRunButton iconOnlyOnMobile />;
}
