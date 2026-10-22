"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ExternalLink, FlaskConical, Globe, Loader2, Play } from "lucide-react";

import { Loadable } from "@/components/async-state";
import { Callout } from "@/components/callout";
import { PageHeader } from "@/components/layout/page-header";
import { DataList, MobileCardHeader, type Column } from "@/components/patterns/data-list";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { ApiError, api, errorMessage, useApi } from "@/lib/api";
import {
  COLLECTION_METHOD_LABELS,
  DASH,
  ERROR_TYPE_LABELS,
  SOURCE_TYPE_LABELS,
  formatNumber,
  formatRelative,
  label,
  safeExternalUrl,
} from "@/lib/format";
import type { Employer, Source, SourceState, SourceTestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATE_TONE: Record<SourceState, StatusTone> = { active: "success", disabled: "neutral", to_verify: "warning", unreachable: "destructive", error: "destructive", excluded: "neutral" };
const STATE_ORDER: SourceState[] = ["active", "disabled", "to_verify", "unreachable", "error", "excluded"];
const STATE_PLURAL: Record<SourceState, string> = {
  active: "Actives",
  disabled: "Désactivées",
  to_verify: "À vérifier",
  unreachable: "Inaccessibles",
  error: "En erreur",
  excluded: "Exclues",
};

export default function SourcesPage() {
  const { data, error, reload } = useApi<Source[]>("/sources", { refreshMs: 30_000 });
  const [filter, setFilter] = useState<SourceState | "all">("all");

  const counts = new Map<SourceState, number>();
  data?.forEach((s) => counts.set(s.state, (counts.get(s.state) ?? 0) + 1));
  const shown = data?.filter((s) => filter === "all" || s.state === filter) ?? [];

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-6">
        <PageHeader
          title="Sources"
          icon={Globe}
          subtitle={data ? `${data.length} source(s) étudiée(s), ${data.filter((s) => s.can_collect).length} avec un connecteur` : "Chargement…"}
        />
        <Loadable error={error} hasData={!!data} onRetry={reload} rows={4}>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrer par état">
            <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>
              Toutes ({data?.length ?? 0})
            </FilterChip>
            {STATE_ORDER.filter((s) => counts.get(s)).map((s) => (
              <FilterChip key={s} active={filter === s} onClick={() => setFilter(s)}>
                {STATE_PLURAL[s]} ({counts.get(s)})
              </FilterChip>
            ))}
          </div>
          <SourcesList sources={shown} onChanged={reload} />
          <Callout title="À propos des sources exclues ou différées">
            Chaque source écartée affiche la raison de la décision (conditions d&rsquo;utilisation, robots.txt, protection anti-robot, accès nécessitant une connexion…). JobRadar ne contourne ni
            CAPTCHA, ni authentification, ni blocage. Pour une offre vue sur une de ces plateformes, utilisez « Ajouter une annonce » dans la page Offres.
          </Callout>
        </Loadable>
      </section>

      <EmployersSection />
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "h-8 rounded-md border px-3 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
        active ? "border-primary bg-primary text-primary-foreground" : "bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
      )}
    >
      {children}
    </button>
  );
}

function SourcesList({ sources, onChanged }: { sources: Source[]; onChanged: () => Promise<void> }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, action: string, fn: () => Promise<void>) {
    setBusy(`${key}:${action}`);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const test = (s: Source) =>
    run(s.key, "test", async () => {
      const r = await api.post<SourceTestResult>(`/sources/${s.key}/test`);
      const latency = r.latency_ms != null ? ` · ${r.latency_ms} ms` : "";
      (r.ok ? toast.success : toast.error)(`${s.name} : ${r.ok ? "accessible" : "problème"} — ${r.detail}${latency}`);
      await onChanged();
    });

  const collect = (s: Source) =>
    run(s.key, "collect", async () => {
      const { id } = await api.post<{ id: number }>(`/sources/${s.key}/collect`);
      toast.success(`Collecte n° ${id} lancée sur ${s.name}.`);
      router.push(`/runs?run=${id}`);
    });

  const toggle = (s: Source, enabled: boolean) =>
    run(s.key, "toggle", async () => {
      await api.patch(`/sources/${s.key}`, { enabled });
      toast.success(`${s.name} : ${enabled ? "activée" : "désactivée"}.`);
      await onChanged();
    });

  const actions = (s: Source, withLabels = false) => (
    <div className="flex items-center justify-end gap-2">
      {s.can_collect ? (
        <>
          <Button variant="outline" size={withLabels ? "sm" : "icon"} className={withLabels ? undefined : "size-8"} disabled={busy !== null} onClick={() => test(s)} aria-label={`Tester ${s.name}`} title="Tester la source (une requête, rien n'est enregistré)">
            {busy === `${s.key}:test` ? <Loader2 className="animate-spin" /> : <FlaskConical />}
            {withLabels && "Tester"}
          </Button>
          <Button variant="secondary" size={withLabels ? "sm" : "icon"} className={withLabels ? undefined : "size-8"} disabled={busy !== null || !s.enabled} onClick={() => collect(s)} aria-label={`Lancer une collecte sur ${s.name}`} title={s.enabled ? "Lancer une collecte sur cette source" : "Activez la source pour la collecter"}>
            {busy === `${s.key}:collect` ? <Loader2 className="animate-spin" /> : <Play />}
            {withLabels && "Collecter"}
          </Button>
        </>
      ) : null}
    </div>
  );

  const columns: Column<Source>[] = [
    {
      key: "name",
      header: "Source",
      cell: (s) => (
        <div className="min-w-0 max-w-56">
          <p className="truncate font-medium">{s.name}</p>
          <a href={safeExternalUrl(s.base_url) ?? undefined} target="_blank" rel="noopener noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-xs text-muted-foreground underline-offset-4 hover:underline">
            <span className="truncate">{s.base_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}</span>
            <ExternalLink className="size-3 shrink-0" aria-hidden="true" />
            <span className="sr-only">(nouvel onglet)</span>
          </a>
        </div>
      ),
    },
    { key: "type", header: "Type · méthode", cell: (s) => (
      <div className="text-xs leading-5">
        <p>
          {label(SOURCE_TYPE_LABELS, s.source_type)} · {s.countries.length ? s.countries.join(", ") : s.market === "remote" ? "télétravail" : DASH}
        </p>
        <p className="text-muted-foreground">{label(COLLECTION_METHOD_LABELS, s.collection_method)}</p>
      </div>
    ) },
    { key: "state", header: "État", cell: (s) => <StateCell s={s} /> },
    { key: "last", header: "Dernière exécution", cell: (s) => (
      <div className="text-xs leading-5">
        <p>{s.last_run_at ? formatRelative(s.last_run_at) : "Jamais"}</p>
        <p className="text-muted-foreground">{s.last_success_at ? `réussie ${formatRelative(s.last_success_at)}` : "aucune réussite"}</p>
      </div>
    ) },
    { key: "offers", header: "Offres", align: "right", cell: (s) => (
      <div className="text-xs leading-5 tabular-nums">
        <p className="text-sm font-medium">{formatNumber(s.offers_count)}</p>
        <p className="text-muted-foreground">{s.errors_count} erreur(s)</p>
      </div>
    ) },
    {
      key: "actions",
      header: "Active · actions",
      align: "right",
      cell: (s) => (
        <div className="flex items-center justify-end gap-3">
          <EnableSwitch s={s} disabled={busy !== null} onToggle={toggle} />
          {actions(s)}
        </div>
      ),
    },
  ];

  if (!sources.length) return <p className="text-sm text-muted-foreground">Aucune source dans cet état.</p>;

  return (
    <DataList
      rows={sources}
      columns={columns}
      rowKey={(s) => s.key}
      mobileCard={(s) => (
        <div>
          <MobileCardHeader name={s.name} subtitle={`${label(SOURCE_TYPE_LABELS, s.source_type)} · ${s.countries.join(", ") || "télétravail"}`} badge={<StatusBadge tone={STATE_TONE[s.state]} label={s.state_label} />} />
          <StateDetails s={s} className="mt-3" />
          <p className="mt-2 text-xs text-muted-foreground">
            {formatNumber(s.offers_count)} offre(s) · {s.errors_count} erreur(s) · dernière exécution {s.last_run_at ? formatRelative(s.last_run_at) : "jamais"}
          </p>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <EnableSwitch s={s} disabled={busy !== null} onToggle={toggle} withLabel />
            {actions(s, true)}
          </div>
        </div>
      )}
    />
  );
}

function EnableSwitch({ s, disabled, onToggle, withLabel }: { s: Source; disabled: boolean; onToggle: (s: Source, v: boolean) => void; withLabel?: boolean }) {
  if (!s.can_collect) return withLabel ? null : <span className="text-xs text-muted-foreground">{DASH}</span>;
  return (
    <label className="inline-flex items-center gap-2 text-sm">
      <Switch checked={s.enabled} disabled={disabled} onCheckedChange={(v) => onToggle(s, v)} aria-label={`${s.enabled ? "Désactiver" : "Activer"} ${s.name}`} />
      {withLabel && <span>{s.enabled ? "Activée" : "Désactivée"}</span>}
    </label>
  );
}

function StateCell({ s }: { s: Source }) {
  return (
    <div className="flex max-w-72 flex-col items-start gap-1.5">
      <StatusBadge tone={STATE_TONE[s.state]} label={s.state_label} />
      <StateDetails s={s} />
    </div>
  );
}

/** Raison affichée sous l'état : dernière erreur, ou décision documentée pour les sources sans connecteur. */
function StateDetails({ s, className }: { s: Source; className?: string }) {
  const text = s.last_error ? `${label(ERROR_TYPE_LABELS, s.last_error_type)} — ${s.last_error}` : !s.can_collect ? s.decision_reason : null;
  if (!text && !s.tos_note) return null;
  return (
    <details className={cn("text-xs text-muted-foreground", className)}>
      <summary className="cursor-pointer list-none underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-ring/50">{s.last_error ? "Voir l'erreur" : "Pourquoi ?"}</summary>
      <div className="mt-1.5 flex flex-col gap-1.5 break-words">
        {text && <p>{text}</p>}
        {s.tos_note && <p>Conditions : {s.tos_note}</p>}
        {s.doc_status && <p>Cartographie : {s.doc_status}</p>}
      </div>
    </details>
  );
}

function EmployersSection() {
  const { data, error, reload } = useApi<Employer[]>("/employers");
  const columns: Column<Employer>[] = [
    { key: "name", header: "Employeur", cell: (e) => <div><p className="font-medium">{e.name}</p><p className="text-xs text-muted-foreground">{e.sector ?? DASH}</p></div> },
    { key: "country", header: "Pays", cell: (e) => e.country ?? DASH },
    { key: "status", header: "Page carrière", cell: (e) => {
      const href = safeExternalUrl(e.career_url);
      return href ? (
        <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm underline underline-offset-4">
          Ouvrir <ExternalLink className="size-3" aria-hidden="true" /> <span className="sr-only">(nouvel onglet)</span>
        </a>
      ) : (
        <span className="text-xs text-muted-foreground">aucune URL vérifiée</span>
      );
    } },
    { key: "method", header: "Collecte", cell: (e) => <span className="text-xs">{e.source_key ? "Connecteur dédié" : "Pas de collecte automatique"}</span> },
    { key: "note", header: "Vérification", cell: (e) => <p className="max-w-md text-xs leading-5 break-words whitespace-normal text-muted-foreground">{e.verification_note ?? DASH}</p> },
  ];
  return (
    <section className="flex flex-col gap-4">
      <PageHeader title={<h2 className="text-xl font-semibold tracking-tight">Employeurs ciblés</h2>} subtitle="Pages carrière vérifiées une à une : aucune URL n'est supposée" icon={Globe} />
      <Loadable error={error} hasData={!!data} onRetry={reload} rows={2}>
        {data && data.length > 0 ? (
          <Card className="gap-0 py-0">
            <CardHeader className="sr-only">
              <CardTitle>Employeurs</CardTitle>
            </CardHeader>
            <CardContent className="p-4 sm:p-5">
              <DataList
                rows={data}
                columns={columns}
                rowKey={(e) => e.key}
                mobileCard={(e) => (
                  <div>
                    <MobileCardHeader name={e.name} subtitle={`${e.sector ?? ""} ${e.country ? `· ${e.country}` : ""}`.trim()} />
                    <p className="mt-3 text-xs break-words text-muted-foreground">{e.verification_note ?? DASH}</p>
                    {safeExternalUrl(e.career_url) && (
                      <a href={safeExternalUrl(e.career_url)!} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-sm underline underline-offset-4">
                        Page carrière <ExternalLink className="size-3" aria-hidden="true" />
                      </a>
                    )}
                  </div>
                )}
              />
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">Aucun employeur dans config/employers.yaml.</p>
        )}
      </Loadable>
    </section>
  );
}
