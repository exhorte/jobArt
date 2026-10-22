"use client";

import { ChevronDown, Loader2 } from "lucide-react";

import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { ERROR_TYPE_LABELS, RUN_SOURCE_STATUS_LABELS, RUN_STATUS_LABELS, formatDateTime, formatDuration, formatNumber, label } from "@/lib/format";
import type { Run, RunSource, RunSourceStatus, RunStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export const RUN_TONE: Record<RunStatus, StatusTone> = { completed: "success", partial: "warning", failed: "destructive", interrupted: "warning", queued: "neutral", running: "neutral" };
const SOURCE_TONE: Record<RunSourceStatus, StatusTone> = { success: "success", failed: "destructive", skipped: "warning", pending: "neutral", running: "neutral" };

export const isActive = (s: RunStatus) => s === "queued" || s === "running";

function Metric({ term, value }: { term: string; value: number }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{term}</dt>
      <dd className="text-sm font-semibold tabular-nums">{formatNumber(value)}</dd>
    </div>
  );
}

/** Une exécution : résumé toujours visible (date, déclencheur, statut, volumes) + détail par source dépliable. */
export function RunCard({ run, defaultOpen = false, highlighted = false }: { run: Run; defaultOpen?: boolean; highlighted?: boolean }) {
  const active = isActive(run.status);
  const done = run.sources.filter((s) => s.status !== "pending" && s.status !== "running").length;
  return (
    <Card className={cn("gap-0 py-0", highlighted && "ring-2 ring-ring/40")}>
      <details className="group" open={defaultOpen || active}>
        <summary className="flex cursor-pointer list-none flex-col gap-3 px-5 py-4 outline-none focus-visible:bg-muted/50 sm:flex-row sm:items-center sm:gap-6">
          <div className="min-w-0 sm:w-56">
            <p className="flex items-center gap-2 text-sm font-medium">
              {active ? <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden="true" /> : null}
              Collecte n° {run.id}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatDateTime(run.started_at)} · {run.trigger_type === "scheduled" ? "veille automatique" : "lancement manuel"}
            </p>
            {run.profile_name && <p className="truncate text-xs text-muted-foreground">Profil : {run.profile_name}</p>}
          </div>
          <div className="flex items-center gap-3 sm:w-40">
            <StatusBadge tone={RUN_TONE[run.status]} label={RUN_STATUS_LABELS[run.status]} />
            <span className="text-xs text-muted-foreground tabular-nums">{active ? `${done}/${run.sources_requested} sources` : formatDuration(run.duration_ms)}</span>
          </div>
          <dl className="grid flex-1 grid-cols-4 gap-3">
            <Metric term="Trouvées" value={run.offers_found} />
            <Metric term="Créées" value={run.offers_created} />
            <Metric term="Mises à jour" value={run.offers_updated} />
            <Metric term="Doublons" value={run.duplicates_detected} />
          </dl>
          <ChevronDown className="hidden size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180 sm:block" aria-hidden="true" />
        </summary>

        <div className="border-t bg-muted/30 px-5 py-4">
          {run.error_summary && <p className="mb-3 text-xs break-words text-muted-foreground">{run.error_summary}</p>}
          <p className="mb-3 text-xs text-muted-foreground">
            {run.sources_succeeded} réussie(s), {run.sources_failed} en échec sur {run.sources_requested} source(s) demandée(s).
          </p>
          <ul className="flex flex-col gap-2">
            {run.sources.map((s) => (
              <SourceLine key={s.source_key} s={s} />
            ))}
          </ul>
        </div>
      </details>
    </Card>
  );
}

function SourceLine({ s }: { s: RunSource }) {
  const warnings = Array.isArray(s.details?.warnings) ? (s.details.warnings as string[]) : [];
  const rejected = Array.isArray(s.details?.rejected_samples) ? (s.details.rejected_samples as string[]) : [];
  const running = s.status === "running";
  return (
    <li className="rounded-lg border bg-card px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="min-w-0 flex-1 truncate font-medium">{s.source_name}</span>
        <StatusBadge tone={SOURCE_TONE[s.status]} label={RUN_SOURCE_STATUS_LABELS[s.status]} />
        {running && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />}
        <span className="text-xs text-muted-foreground tabular-nums">{formatDuration(s.duration_ms)}</span>
      </div>
      {(s.status === "success" || s.offers_found > 0) && (
        <p className="mt-1.5 text-xs text-muted-foreground tabular-nums">
          {s.offers_found} trouvée(s) · {s.offers_created} créée(s) · {s.offers_updated} mise(s) à jour · {s.duplicates_detected} doublon(s)
          {s.offers_rejected ? ` · ${s.offers_rejected} rejetée(s)` : ""} · {s.requests_made} requête(s)
          {s.status === "success" && s.offers_found === 0 ? " — réponse vide (ce n'est pas une erreur)" : ""}
        </p>
      )}
      {(s.error_type || s.error_message) && (
        <p className="mt-1.5 text-xs break-words">
          <span className={cn("font-medium", s.status === "failed" ? "text-destructive" : "text-warning")}>{label(ERROR_TYPE_LABELS, s.error_type)}</span>
          {s.error_message ? ` — ${s.error_message}` : ""}
        </p>
      )}
      {warnings.length > 0 && <p className="mt-1.5 text-xs break-words text-muted-foreground">Avertissements : {warnings.join(" ; ")}</p>}
      {rejected.length > 0 && <p className="mt-1.5 text-xs break-words text-muted-foreground">Exemples d&rsquo;annonces rejetées : {rejected.join(" ; ")}</p>}
    </li>
  );
}
