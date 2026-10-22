"use client";

import { useState } from "react";
import Link from "next/link";
import { Activity, CalendarClock, Clock, HeartPulse, Loader2, Radar, Timer } from "lucide-react";

import { Loadable } from "@/components/async-state";
import { Callout } from "@/components/callout";
import { Field } from "@/components/field";
import { PageHeader } from "@/components/layout/page-header";
import { LaunchRunButton } from "@/components/launch-run-button";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/metric-panel";
import { SplitLayout } from "@/components/patterns/split-layout";
import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { api, errorMessage, useApi } from "@/lib/api";
import { DASH, RUN_STATUS_LABELS, SCHEDULER_STATE_LABELS, formatDateTime, formatInterval, formatRelative } from "@/lib/format";
import type { Profile, SchedulerSettings, Source } from "@/lib/types";

const TONE: Record<SchedulerSettings["state"], StatusTone> = { running: "success", stopped: "warning", disabled: "neutral" };
const PRESETS = [30, 60, 180, 360, 720, 1440, 2880, 10080];

export default function SchedulerPage() {
  const { data, error, reload } = useApi<SchedulerSettings>("/settings/scheduler", { refreshMs: 15_000 });
  const { data: profiles } = useApi<Profile[]>("/search-profiles");
  const { data: sources } = useApi<Source[]>("/sources");

  return (
    <Loadable error={error} hasData={!!data} onRetry={reload} rows={3}>
      {data && <SchedulerView s={data} profiles={profiles ?? []} sources={(sources ?? []).filter((x) => x.can_collect)} reload={reload} />}
    </Loadable>
  );
}

function stateExplanation(s: SchedulerSettings): string {
  if (s.state === "running") {
    return s.this_process_is_leader
      ? "Le processus de l'API porte la veille : il a battu récemment et détient le bail. La collecte part automatiquement à l'échéance."
      : "Un processus dédié (worker) porte la veille : il a battu récemment et détient le bail. La collecte part automatiquement à l'échéance.";
  }
  if (s.state === "stopped") {
    return s.mode === "off"
      ? "La veille est activée, mais aucun processus ne la porte : l'API est en mode « off » et aucun worker ne tourne. Aucune collecte automatique n'aura lieu tant que vous n'aurez pas lancé « python -m jobart.jobs.worker »."
      : "La veille est activée, mais aucun battement récent : le processus qui la porte est arrêté. Aucune collecte automatique n'aura lieu tant qu'il ne redémarre pas ; au redémarrage, une seule collecte de rattrapage est lancée.";
  }
  return "La veille est désactivée : jobArt ne collecte que lorsque vous le demandez.";
}

function SchedulerView({ s, profiles, sources, reload }: { s: SchedulerSettings; profiles: Profile[]; sources: Source[]; reload: () => Promise<void> }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const preset = PRESETS.includes(s.interval_minutes);
  const [intervalChoice, setIntervalChoice] = useState<string>(preset ? String(s.interval_minutes) : "custom");
  const [customMinutes, setCustomMinutes] = useState(String(s.interval_minutes));
  const [profileIds, setProfileIds] = useState<number[]>(s.profile_ids ?? []);
  const [sourceKeys, setSourceKeys] = useState<string[]>(s.source_keys ?? []);

  const minutes = intervalChoice === "custom" ? Number(customMinutes) : Number(intervalChoice);
  const intervalValid = Number.isInteger(minutes) && minutes >= s.min_interval_minutes && minutes <= s.max_interval_minutes;
  const dirty = minutes !== s.interval_minutes || JSON.stringify([...profileIds].sort()) !== JSON.stringify([...(s.profile_ids ?? [])].sort()) || JSON.stringify([...sourceKeys].sort()) !== JSON.stringify([...(s.source_keys ?? [])].sort());

  async function patch(body: Record<string, unknown>, key: string, ok: string) {
    setBusy(key);
    try {
      await api.patch("/settings/scheduler", body);
      await reload();
      toast.success(ok);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const toggle = (v: boolean) => patch({ enabled: v }, "enabled", v ? "Veille activée : la première collecte part au prochain passage du planificateur." : "Veille désactivée.");
  const save = () => patch({ interval_minutes: minutes, profile_ids: profileIds.length ? profileIds : null, source_keys: sourceKeys.length ? sourceKeys : null }, "save", "Réglages de la veille enregistrés.");

  const flip = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  return (
    <SplitLayout
      stickyAside
      asideFirstOnMobile
      main={
        <>
          <PageHeader title="Veille automatique" icon={Radar} subtitle="Collecte périodique des sources activées, sans intervention" actions={<LaunchRunButton variant="outline">Lancer une collecte maintenant</LaunchRunButton>} />

          <Card className="gap-4">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-3 text-sm font-semibold">
                  État réel <StatusBadge tone={TONE[s.state]} label={SCHEDULER_STATE_LABELS[s.state]} />
                </CardTitle>
                <label className="inline-flex items-center gap-3 text-sm font-medium">
                  <span id="sched-switch-label">{s.enabled ? "Activée" : "Désactivée"}</span>
                  <Switch checked={s.enabled} disabled={busy !== null} onCheckedChange={toggle} aria-labelledby="sched-switch-label" />
                </label>
              </div>
              <CardDescription className="text-sm leading-6">{stateExplanation(s)}</CardDescription>
            </CardHeader>
          </Card>

          {s.last_error && (
            <Callout title="Dernier déclenchement en erreur" variant="warning">
              <span className="break-words">{s.last_error}</span>
            </Callout>
          )}

          <Card className="gap-5">
            <CardHeader>
              <CardTitle className="text-sm font-semibold">Fréquence et périmètre</CardTitle>
              <CardDescription>Ces réglages sont conservés après un redémarrage. Certaines sources imposent un intervalle minimal entre deux collectes : elles sont ignorées (et signalées dans l&rsquo;historique) si elles ont été collectées trop récemment.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field id="sched-interval" label="Intervalle entre deux collectes" hint={`De ${formatInterval(s.min_interval_minutes)} à ${formatInterval(s.max_interval_minutes)}.`}>
                  <Select id="sched-interval" value={intervalChoice} onChange={(e) => setIntervalChoice(e.target.value)}>
                    {PRESETS.map((m) => (
                      <option key={m} value={m}>
                        Toutes les {formatInterval(m)}
                        {m === 360 ? " (recommandé)" : ""}
                      </option>
                    ))}
                    <option value="custom">Personnalisé…</option>
                  </Select>
                </Field>
                {intervalChoice === "custom" && (
                  <Field id="sched-custom" label="Minutes" error={!intervalValid ? `Entre ${s.min_interval_minutes} et ${s.max_interval_minutes} minutes.` : null}>
                    <Input id="sched-custom" type="number" inputMode="numeric" min={s.min_interval_minutes} max={s.max_interval_minutes} value={customMinutes} onChange={(e) => setCustomMinutes(e.target.value)} aria-invalid={!intervalValid} />
                  </Field>
                )}
              </div>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-[13px] font-medium">Profils concernés</legend>
                <p className="text-xs text-muted-foreground">{profileIds.length ? `${profileIds.length} profil(s) choisi(s).` : "Aucun choix : tous les profils actifs sont utilisés."}</p>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {profiles.map((p) => (
                    <label key={p.id} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="size-4 accent-foreground" checked={profileIds.includes(p.id)} onChange={() => setProfileIds((cur) => flip(cur, p.id))} />
                      <span className="truncate">
                        {p.name}
                        {!p.is_active && <span className="text-muted-foreground"> (inactif)</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset className="flex flex-col gap-2">
                <legend className="text-[13px] font-medium">Sources concernées</legend>
                <p className="text-xs text-muted-foreground">{sourceKeys.length ? `${sourceKeys.length} source(s) choisie(s).` : "Aucun choix : toutes les sources activées sont collectées."}</p>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  {sources.map((x) => (
                    <label key={x.key} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" className="size-4 accent-foreground" checked={sourceKeys.includes(x.key)} onChange={() => setSourceKeys((cur) => flip(cur, x.key))} />
                      <span className="truncate">
                        {x.name}
                        {!x.enabled && <span className="text-muted-foreground"> (désactivée)</span>}
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              <div>
                <Button disabled={!dirty || !intervalValid || busy !== null} onClick={save}>
                  {busy === "save" && <Loader2 className="animate-spin" />} Enregistrer les réglages
                </Button>
              </div>
            </CardContent>
          </Card>
        </>
      }
      aside={
        <>
          <HighlightBar icon={Timer} value={`Toutes les ${formatInterval(s.interval_minutes)}`} label="intervalle" />
          <MetricPanel>
            <MetricPanelItem label="Prochaine exécution" value={s.enabled && s.next_run_at ? formatRelative(s.next_run_at) : DASH} icon={CalendarClock} solidIcon hint={s.enabled && s.next_run_at ? formatDateTime(s.next_run_at) : s.enabled ? "calculée au prochain passage" : "veille désactivée"} />
            <MetricPanelItem
              label="Dernière exécution automatique"
              value={s.last_run_at ? formatRelative(s.last_run_at) : "Aucune"}
              icon={Clock}
              hint={
                s.last_run_id ? (
                  <Link href={`/runs?run=${s.last_run_id}`} className="underline underline-offset-4">
                    n° {s.last_run_id} · {s.last_run_status ? RUN_STATUS_LABELS[s.last_run_status as keyof typeof RUN_STATUS_LABELS] ?? s.last_run_status : "—"}
                  </Link>
                ) : undefined
              }
            />
            <MetricPanelItem label="Battement de cœur" value={s.heartbeat_at ? formatRelative(s.heartbeat_at) : "Aucun"} icon={HeartPulse} tone={s.alive ? "success" : s.enabled ? "warning" : undefined} hint={s.alive ? "un processus porte la veille" : "aucun processus actif"} />
            <MetricPanelItem label="Mode du planificateur" value={s.mode === "embedded" ? "Dans l'API" : "Worker dédié"} icon={Activity} hint={s.mode === "embedded" ? "SCHEDULER_MODE=embedded" : "SCHEDULER_MODE=off"} />
          </MetricPanel>
        </>
      }
    />
  );
}
