/** Formats d'affichage (fr-FR) et libellés des vocabulaires du backend. Aucune donnée n'est inventée : absent → « — ». */

import type { Freshness, LifecycleStatus, RunSourceStatus, RunStatus, UserStatus, WorkMode } from "@/lib/types";

const LOCALE = "fr-FR";
export const DASH = "—";

const dateFmt = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const numberFmt = new Intl.NumberFormat(LOCALE);

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

export const formatDate = (iso: string | null | undefined) => {
  const d = parse(iso);
  return d ? dateFmt.format(d) : DASH;
};

export const formatDateTime = (iso: string | null | undefined) => {
  const d = parse(iso);
  return d ? dateTimeFmt.format(d) : DASH;
};

export const formatNumber = (n: number | null | undefined) => (n == null ? DASH : numberFmt.format(n));

/** « il y a 5 min », « dans 2 h » — pour les horodatages récents ou à venir. */
export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  const d = parse(iso);
  if (!d) return DASH;
  const diffSec = Math.round((d.getTime() - now) / 1000);
  const abs = Math.abs(diffSec);
  const rtf = new Intl.RelativeTimeFormat(LOCALE, { numeric: "auto" });
  if (abs < 60) return rtf.format(Math.sign(diffSec) * Math.max(abs, 1), "second");
  if (abs < 3600) return rtf.format(Math.round(diffSec / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffSec / 3600), "hour");
  if (abs < 86400 * 30) return rtf.format(Math.round(diffSec / 86400), "day");
  return formatDate(iso);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return DASH;
  if (ms < 1000) return `${ms} ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${String(s % 60).padStart(2, "0")} s`;
}

export function formatInterval(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? "24 h" : `${minutes / 1440} j`;
  if (minutes % 60 === 0) return `${minutes / 60} h`;
  return `${minutes} min`;
}

export function formatSalary(o: { salary_min: number | null; salary_max: number | null; salary_currency: string | null; salary_period: string | null }): string | null {
  if (o.salary_min == null && o.salary_max == null) return null;
  const cur = o.salary_currency ?? "";
  const range = o.salary_min != null && o.salary_max != null && o.salary_min !== o.salary_max
    ? `${numberFmt.format(o.salary_min)} – ${numberFmt.format(o.salary_max)}`
    : numberFmt.format((o.salary_min ?? o.salary_max)!);
  return `${range} ${cur}${o.salary_period ? ` / ${o.salary_period}` : ""}`.trim();
}

export function formatScore(score: number | null | undefined): string {
  return score == null ? DASH : String(Math.round(score));
}

// ------------------------------------------------------------------------------------------------ libellés
export const CONTRACT_LABELS: Record<string, string> = {
  cdi: "CDI",
  cdd: "CDD",
  stage: "Stage",
  freelance: "Freelance",
  alternance: "Alternance",
  interim: "Intérim",
  full_time: "Temps plein",
  part_time: "Temps partiel",
  contract: "Contrat",
};

export const WORK_MODE_LABELS: Record<WorkMode, string> = { onsite: "Sur site", hybrid: "Hybride", remote: "Télétravail" };

export const EXPERIENCE_LABELS: Record<string, string> = {
  intern: "Stagiaire",
  junior: "Junior",
  mid: "Confirmé",
  senior: "Senior",
  lead: "Lead / manager",
};

export const USER_STATUS_LABELS: Record<UserStatus, string> = {
  new: "Nouvelle",
  seen: "Vue",
  saved: "Sauvegardée",
  applied: "Candidature envoyée",
  ignored: "Ignorée",
};

export const LIFECYCLE_LABELS: Record<LifecycleStatus, string> = {
  listed: "Visible à la dernière collecte",
  stale: "Plus vue récemment",
  deadline_passed: "Date limite dépassée",
  closed: "Clôturée par la source",
};

export const FRESHNESS_LABELS: Record<Freshness["label"], string> = {
  fresh: "Récente",
  recent: "Assez récente",
  old: "Ancienne",
  unknown_date: "Date inconnue",
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: "En file",
  running: "En cours",
  completed: "Terminée",
  partial: "Partielle",
  failed: "Échec",
  interrupted: "Interrompue",
};

export const RUN_SOURCE_STATUS_LABELS: Record<RunSourceStatus, string> = {
  pending: "En attente",
  running: "En cours",
  success: "Réussie",
  failed: "Échec",
  skipped: "Ignorée",
};

export const ERROR_TYPE_LABELS: Record<string, string> = {
  network: "Réseau",
  timeout: "Délai dépassé",
  unavailable: "Indisponible",
  blocked: "Accès bloqué",
  rate_limited: "Limite de requêtes",
  robots_disallowed: "Interdit par robots.txt",
  parse: "Structure modifiée",
  normalization: "Annonce rejetée",
  locked: "Déjà en cours",
  skipped_recent: "Collectée récemment",
  internal: "Erreur interne",
};

export const SOURCE_TYPE_LABELS: Record<string, string> = {
  job_board: "Site d'emploi",
  aggregator: "Agrégateur",
  employer_career: "Page carrière",
  api: "API publique",
  newsletter: "Newsletter",
  manual: "Saisie manuelle",
};

export const COLLECTION_METHOD_LABELS: Record<string, string> = {
  html_list: "Pages HTML (liste)",
  html_list_article: "Pages HTML (liste + détail)",
  html_list_jsonld: "Liste HTML + JSON-LD du détail",
  json_endpoint_html: "Endpoint JSON + HTML",
  json_api: "API JSON publique",
  rss: "Flux RSS",
  manual: "Saisie manuelle",
  none: "Aucune collecte",
  unknown: "Non déterminée",
};

export const SCHEDULER_STATE_LABELS = {
  disabled: "Désactivée",
  running: "Active",
  stopped: "Activée, mais arrêtée",
} as const;

export const label = (map: Record<string, string>, key: string | null | undefined): string => (key ? (map[key] ?? key) : DASH);

export function scoreTone(score: number | null | undefined): "success" | "warning" | "neutral" {
  if (score == null) return "neutral";
  if (score >= 70) return "success";
  if (score >= 50) return "warning";
  return "neutral";
}

/** Ouvre une URL externe uniquement si elle est en http(s) (les URLs viennent de sites tiers : jamais `javascript:`). */
export function safeExternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:" ? u.toString() : null;
  } catch {
    return null;
  }
}
