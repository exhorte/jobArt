"use client";

import Link from "next/link";
import { ExternalLink } from "lucide-react";

import { ContractBadge, UserStatusBadge, WorkModeBadge } from "@/components/offer-badges";
import { DataList, MobileCardHeader, type Column } from "@/components/patterns/data-list";
import { ScoreBadge } from "@/components/score-badge";
import { Button } from "@/components/ui/button";
import { DASH, formatDate, safeExternalUrl } from "@/lib/format";
import type { OfferListItem } from "@/lib/types";

function OfferTitle({ o }: { o: OfferListItem }) {
  const place = [o.city ?? o.location, o.country].filter(Boolean).join(", ");
  return (
    <div className="min-w-0 max-w-[19rem]">
      <Link href={`/offers/${o.id}`} className="block truncate font-medium underline-offset-4 hover:underline focus-visible:underline" title={o.title}>
        {o.title}
      </Link>
      <p className="truncate text-xs text-muted-foreground">
        {o.company_name ?? "Entreprise non précisée"}
        {place ? ` · ${place}` : ""}
      </p>
    </div>
  );
}

function OpenButton({ o, withDetail = false }: { o: OfferListItem; withDetail?: boolean }) {
  const href = safeExternalUrl(o.primary_url);
  const source = o.sources[0]?.name ?? "la source";
  return (
    <div className="flex items-center justify-end gap-2">
      {withDetail && (
        <Button asChild variant="secondary" size="sm">
          <Link href={`/offers/${o.id}`}>Détail</Link>
        </Button>
      )}
      {href ? (
        <Button asChild variant="outline" size="sm">
          <a href={href} target="_blank" rel="noopener noreferrer" aria-label={`Ouvrir l'annonce d'origine sur ${source} (nouvel onglet)`}>
            <ExternalLink /> Ouvrir
          </a>
        </Button>
      ) : null}
    </div>
  );
}

const sourcesOf = (o: OfferListItem) => (o.sources.length ? o.sources.map((s) => s.name).join(", ") : DASH);

const FULL_COLUMNS: Column<OfferListItem>[] = [
  { key: "offer", header: "Offre", cell: (o) => <OfferTitle o={o} /> },
  {
    key: "mode",
    header: "Contrat · mode",
    cell: (o) => (
      <div className="flex flex-wrap gap-1">
        <ContractBadge value={o.contract_type} />
        <WorkModeBadge value={o.work_mode} />
        {!o.contract_type && !o.work_mode && DASH}
      </div>
    ),
  },
  {
    key: "dates",
    header: "Publiée · détectée",
    cell: (o) => (
      <div className="text-xs leading-5">
        <p title="Date de publication déclarée par la source">{o.published_at ? formatDate(o.published_at) : "Date inconnue"}</p>
        <p className="text-muted-foreground" title="Première détection par jobArt">
          vue le {formatDate(o.first_seen_at)}
        </p>
      </div>
    ),
  },
  { key: "source", header: "Source", cell: (o) => <span className="block max-w-28 truncate text-sm" title={sourcesOf(o)}>{sourcesOf(o)}</span> },
  { key: "score", header: "Score", cell: (o) => <ScoreBadge score={o.score} /> },
  { key: "status", header: "Statut", cell: (o) => <UserStatusBadge status={o.user_status} /> },
  { key: "action", header: "Action", align: "right", cell: (o) => <OpenButton o={o} /> },
];

const COMPACT_COLUMNS: Column<OfferListItem>[] = [
  FULL_COLUMNS[0],
  { key: "source", header: "Source", cell: FULL_COLUMNS[3].cell },
  { key: "dates", header: "Détectée", cell: (o) => <span className="text-xs">{formatDate(o.first_seen_at)}</span> },
  FULL_COLUMNS[4],
  { key: "action", header: "Action", align: "right", cell: (o) => <OpenButton o={o} /> },
];

/** Liste d'offres : tableau à en-tête sombre dès `md`, cartes dessous. `compact` pour les aperçus du tableau de bord. */
export function OffersTable({ offers, compact = false }: { offers: OfferListItem[]; compact?: boolean }) {
  return (
    <DataList
      rows={offers}
      columns={compact ? COMPACT_COLUMNS : FULL_COLUMNS}
      rowKey={(o) => String(o.id)}
      mobileCard={(o) => (
        <div>
          <MobileCardHeader
            name={o.title}
            subtitle={`${o.company_name ?? "Entreprise non précisée"}${o.city ? ` · ${o.city}` : ""}`}
            badge={<ScoreBadge score={o.score} />}
          />
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <ContractBadge value={o.contract_type} />
            <WorkModeBadge value={o.work_mode} />
            <UserStatusBadge status={o.user_status} />
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {o.published_at ? `Publiée le ${formatDate(o.published_at)}` : "Date de publication inconnue"} · vue le {formatDate(o.first_seen_at)} · {sourcesOf(o)}
          </p>
          <div className="mt-3">
            <OpenButton o={o} withDetail />
          </div>
        </div>
      )}
    />
  );
}
