"use client";

import Link from "next/link";
import { Activity, ArrowUpRight, Briefcase, Bookmark, Clock, Globe, Radar, Sparkles } from "lucide-react";

import { Loadable } from "@/components/async-state";
import { BarList } from "@/components/bar-list";
import { Callout } from "@/components/callout";
import { EmptyState } from "@/components/empty-state";
import { LaunchRunButton } from "@/components/launch-run-button";
import { HighlightBar, MetricPanel, MetricPanelItem, MetricPanelList } from "@/components/metric-panel";
import { OffersTable } from "@/components/offers-table";
import { SplitLayout } from "@/components/patterns/split-layout";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/page-header";
import { useApi } from "@/lib/api";
import {
  ERROR_TYPE_LABELS,
  RUN_STATUS_LABELS,
  SCHEDULER_STATE_LABELS,
  WORK_MODE_LABELS,
  formatDateTime,
  formatInterval,
  formatNumber,
  formatRelative,
  label,
} from "@/lib/format";
import type { Dashboard, RunStatus } from "@/lib/types";

const RUN_TONE: Record<RunStatus, StatusTone> = { completed: "success", partial: "warning", failed: "destructive", interrupted: "warning", queued: "neutral", running: "neutral" };

export default function DashboardPage() {
  const { data, error, reload } = useApi<Dashboard>("/dashboard", {
    // Cadence adaptative : 5 s pendant une collecte, 60 s sinon.
    refreshMs: (d) => ((d as Dashboard | undefined)?.last_run?.status === "running" || (d as Dashboard | undefined)?.last_run?.status === "queued" ? 5_000 : 60_000),
  });

  return (
    <div className="flex flex-col gap-10">
      <Loadable error={error} hasData={!!data} onRetry={reload} rows={4}>
        {data && <DashboardView d={data} />}
      </Loadable>
    </div>
  );
}

function DashboardView({ d }: { d: Dashboard }) {
  const empty = d.total_offers === 0;
  const lastRun = d.last_run;
  const sched = d.scheduler;

  return (
    <>
      <SplitLayout
        main={
          <>
            <PageHeader
              title="Tableau de bord"
              icon={Clock}
              subtitle={lastRun ? `Dernière collecte ${formatRelative(lastRun.finished_at ?? lastRun.started_at)}` : "Aucune collecte lancée pour l'instant"}
            />
            {empty ? (
              <EmptyState
                icon={Briefcase}
                action={<LaunchRunButton variant="outline" size="lg" />}
                hint={lastRun ? "La dernière collecte n'a enregistré aucune offre : consultez l'historique pour le détail par source." : "jobArt ne contient aucune offre : lancez une première collecte sur vos sources activées."}
              />
            ) : (
              <WorkCard d={d} />
            )}
          </>
        }
        aside={
          <>
            <HighlightBar icon={Briefcase} value={formatNumber(d.total_offers)} label="offres uniques" />
            <MetricPanel>
              <MetricPanelItem label="Nouvelles offres" value={formatNumber(d.new_offers)} icon={Sparkles} solidIcon hint="non encore consultées" />
              <MetricPanelItem label="Détectées ces 24 h" value={formatNumber(d.detected_24h)} icon={Activity} hint={`${formatNumber(d.recently_detected_7d)} sur 7 jours`} />
              <MetricPanelItem label="Sauvegardées" value={formatNumber(d.saved_offers)} icon={Bookmark} hint={`${formatNumber(d.applied_offers)} candidature(s) envoyée(s)`} />
              <MetricPanelItem label="Sources actives" value={formatNumber(d.active_sources)} unit={`/ ${d.total_connectors}`} icon={Globe} tone={d.sources_in_error.length ? "warning" : undefined} />
              <MetricPanelList
                items={[
                  { label: "Dernière collecte", value: lastRun ? RUN_STATUS_LABELS[lastRun.status] : DASH_TEXT },
                  { label: "Veille", value: SCHEDULER_STATE_LABELS[sched.state] },
                ]}
              />
            </MetricPanel>
          </>
        }
      />

      {d.sources_in_error.length > 0 && (
        <Callout title={`${d.sources_in_error.length} source(s) en erreur ou inaccessible(s)`} variant="warning">
          <ul className="flex flex-col gap-1.5">
            {d.sources_in_error.map((s) => (
              <li key={s.key}>
                <span className="font-medium text-foreground">{s.name}</span> — {label(ERROR_TYPE_LABELS, s.error_type)}
                {s.error ? <span className="break-words"> : {s.error}</span> : null}
              </li>
            ))}
          </ul>
          <Link href="/sources" className="mt-2 inline-block font-medium text-foreground underline underline-offset-4">
            Ouvrir la page Sources
          </Link>
        </Callout>
      )}

      {!empty && (
        <section className="flex flex-col gap-4">
          <PageHeader title={<h2 className="text-xl font-semibold tracking-tight">Détectées récemment</h2>} subtitle="Les plus récentes d'après la première détection par jobArt" icon={Clock} />
          <OffersTable offers={d.recent} compact />
          <div>
            <Button asChild variant="secondary">
              <Link href="/offers">
                Toutes les offres <ArrowUpRight />
              </Link>
            </Button>
          </div>
        </section>
      )}

      {!empty && (d.by_source.length > 0 || d.by_work_mode.length > 0 || d.by_sector.length > 0) && (
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {d.by_source.length > 0 && (
            <Distribution title="Par source" items={d.by_source.map((s) => ({ label: s.source, count: s.count }))} note="Une offre publiée sur plusieurs sources est comptée pour chacune." />
          )}
          {d.by_sector.length > 0 && <Distribution title="Par secteur" items={d.by_sector.map((s) => ({ label: s.sector, count: s.count }))} note="Secteur déduit de l'annonce quand il est identifiable." />}
          {d.by_work_mode.length > 0 && (
            <Distribution
              title="Par mode de travail"
              items={d.by_work_mode.map((s) => ({ label: WORK_MODE_LABELS[s.work_mode as keyof typeof WORK_MODE_LABELS] ?? "Non précisé", count: s.count }))}
              note="« Non précisé » : la source n'indique pas le mode."
            />
          )}
        </section>
      )}

      <Callout title="Important">
        Le score est un indicateur de pertinence calculé à partir de votre profil (métier, compétences, lieu, expérience, secteur, contrat). Il ne dit rien de vos chances d&rsquo;être
        retenu. Une annonce « visible » a simplement été vue à la dernière collecte : vérifiez toujours sur le site d&rsquo;origine qu&rsquo;elle est encore ouverte.
      </Callout>
    </>
  );
}

const DASH_TEXT = "—";

function WorkCard({ d }: { d: Dashboard }) {
  const lastRun = d.last_run;
  const sched = d.scheduler;
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="border-b px-6 py-4">
        <CardTitle className="text-sm font-semibold">Meilleures correspondances</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {d.top_matches.length ? (
          <ul className="divide-y">
            {d.top_matches.map((o) => (
              <li key={o.id} className="flex items-center gap-3 px-6 py-3">
                <div className="min-w-0 flex-1">
                  <Link href={`/offers/${o.id}`} className="block truncate text-sm font-medium underline-offset-4 hover:underline">
                    {o.title}
                  </Link>
                  <p className="truncate text-xs text-muted-foreground">
                    {o.company_name ?? "Entreprise non précisée"}
                    {o.city ? ` · ${o.city}` : ""}
                  </p>
                </div>
                <span className="shrink-0 text-sm font-semibold tabular-nums">{Math.round(o.score ?? 0)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-6 py-6 text-sm text-muted-foreground">Aucune offre n&rsquo;a de score : activez au moins un profil de recherche.</p>
        )}
        <dl className="grid grid-cols-1 gap-x-6 gap-y-3 border-t bg-muted/40 px-6 py-4 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Dernière collecte</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-2">
              {lastRun ? (
                <>
                  <StatusBadge tone={RUN_TONE[lastRun.status]} label={RUN_STATUS_LABELS[lastRun.status]} />
                  <Link href={`/runs?run=${lastRun.id}`} className="text-xs text-muted-foreground underline underline-offset-4">
                    {formatDateTime(lastRun.started_at)}
                  </Link>
                </>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Veille automatique</dt>
            <dd className="mt-1 flex flex-wrap items-center gap-2">
              <Radar className="size-4 text-muted-foreground" aria-hidden="true" />
              <Link href="/scheduler" className="underline-offset-4 hover:underline">
                {SCHEDULER_STATE_LABELS[sched.state]}
              </Link>
              {sched.enabled && <span className="text-xs text-muted-foreground">toutes les {formatInterval(sched.interval_minutes)}</span>}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function Distribution({ title, items, note }: { title: string; items: { label: string; count: number }[]; note: string }) {
  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <BarList items={items.slice(0, 8)} />
        <p className="text-xs text-muted-foreground">{note}</p>
      </CardContent>
    </Card>
  );
}
