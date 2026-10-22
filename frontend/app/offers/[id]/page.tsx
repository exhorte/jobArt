"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Bookmark, ExternalLink, Eye, EyeOff, Gauge, Loader2, Send, Sparkles } from "lucide-react";

import { Loadable } from "@/components/async-state";
import { Callout } from "@/components/callout";
import { PageHeader } from "@/components/layout/page-header";
import { HighlightBar } from "@/components/metric-panel";
import { ContractBadge, FreshnessBadge, LifecycleBadge, UserStatusBadge, WorkModeBadge } from "@/components/offer-badges";
import { SplitLayout } from "@/components/patterns/split-layout";
import { useToast } from "@/components/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, errorMessage, useApi } from "@/lib/api";
import { DASH, EXPERIENCE_LABELS, USER_STATUS_LABELS, formatDate, formatDateTime, formatSalary, label, safeExternalUrl } from "@/lib/format";
import type { OfferDetail, OfferScore, UserStatus } from "@/lib/types";

const STATUS_ACTIONS: { value: UserStatus; icon: typeof Eye }[] = [
  { value: "new", icon: Sparkles },
  { value: "seen", icon: Eye },
  { value: "saved", icon: Bookmark },
  { value: "applied", icon: Send },
  { value: "ignored", icon: EyeOff },
];

const ESTIMATED_LABELS: Record<string, string> = {
  country: "pays",
  city: "ville",
  work_mode: "mode de travail",
  contract_type: "contrat",
  experience_level: "niveau d'expérience",
  sector: "secteur",
  remote_eligibility: "éligibilité télétravail",
};

export default function OfferDetailPage() {
  const params = useParams<{ id: string }>();
  const id = /^\d+$/.test(params.id) ? params.id : null;
  const { data, error, reload, setData } = useApi<OfferDetail>(id ? `/offers/${id}` : null);

  if (!id) return <Callout title="Annonce introuvable" variant="warning">Identifiant d&rsquo;annonce invalide. <Link href="/offers" className="font-medium text-foreground underline underline-offset-4">Retour aux offres</Link></Callout>;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-3">
          <Link href="/offers">
            <ArrowLeft /> Toutes les offres
          </Link>
        </Button>
      </div>
      <Loadable error={error} hasData={!!data && String(data.id) === id} onRetry={reload} rows={4}>
        {data && String(data.id) === id && <OfferView offer={data} onChange={(o) => setData(() => o)} />}
      </Loadable>
    </div>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{term}</dt>
      <dd className="min-w-0 break-words text-sm font-medium">{children}</dd>
    </div>
  );
}

function OfferView({ offer: o, onChange }: { offer: OfferDetail; onChange: (o: OfferDetail) => void }) {
  const external = safeExternalUrl(o.primary_url);
  const salary = formatSalary(o);
  const place = [o.city, o.country].filter(Boolean).join(", ") || o.location;

  return (
    <SplitLayout
      stickyAside
      asideFirstOnMobile
      main={
        <>
          <PageHeader
            title={<h1 className="text-2xl font-semibold tracking-tight break-words sm:text-[28px]">{o.title}</h1>}
            subtitle={`${o.company_name ?? "Entreprise non précisée"}${place ? ` · ${place}` : ""}`}
            icon={Gauge}
            actions={
              external ? (
                <Button asChild>
                  <a href={external} target="_blank" rel="noopener noreferrer">
                    <ExternalLink /> Ouvrir l&rsquo;annonce d&rsquo;origine
                  </a>
                </Button>
              ) : null
            }
          />
          <div className="flex flex-wrap items-center gap-2">
            <UserStatusBadge status={o.user_status} />
            <ContractBadge value={o.contract_type} />
            <WorkModeBadge value={o.work_mode} />
            {o.experience_level && <Badge variant="outline">{label(EXPERIENCE_LABELS, o.experience_level)}</Badge>}
            <FreshnessBadge freshness={o.freshness} />
            <LifecycleBadge status={o.lifecycle_status} />
          </div>

          <Card className="gap-0 py-0">
            <CardHeader className="border-b px-6 py-4">
              <CardTitle className="text-sm font-semibold">Informations</CardTitle>
            </CardHeader>
            <CardContent className="px-6 py-5">
              <dl className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
                <Fact term="Publication (déclarée par la source)">{o.published_at ? formatDate(o.published_at) : "Date inconnue"}</Fact>
                <Fact term="Première détection par jobArt">{formatDateTime(o.first_seen_at)}</Fact>
                <Fact term="Dernière observation">{formatDateTime(o.last_seen_at)}</Fact>
                <Fact term="Date limite de candidature">{o.application_deadline ? formatDate(o.application_deadline) : "Non précisée"}</Fact>
                <Fact term="Salaire annoncé">{salary ?? "Non précisé"}</Fact>
                <Fact term="Secteur">{o.sector ?? DASH}</Fact>
                {o.work_mode === "remote" && (
                  <Fact term="Éligibilité télétravail">
                    {o.remote_eligibility ?? "Non précisée"}
                    {o.remote_regions.length ? ` (${o.remote_regions.join(", ")})` : ""}
                  </Fact>
                )}
                <Fact term="Dernière vérification de la page">{o.last_verified_at ? formatDateTime(o.last_verified_at) : "Non vérifiée individuellement"}</Fact>
              </dl>
              {o.estimated_fields.length > 0 && (
                <p className="mt-4 text-xs text-muted-foreground">
                  Déduit par jobArt à partir du texte (non déclaré par la source) : {o.estimated_fields.map((f) => ESTIMATED_LABELS[f] ?? f).join(", ")}.
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="gap-0 py-0">
            <CardHeader className="border-b px-6 py-4">
              <CardTitle className="text-sm font-semibold">Description</CardTitle>
            </CardHeader>
            <CardContent className="px-6 py-5">
              {o.description ? (
                // Texte tiers non fiable : affiché comme texte brut, jamais interprété comme du HTML.
                <p className="text-sm leading-6 break-words whitespace-pre-wrap">{o.description}</p>
              ) : (
                <p className="text-sm text-muted-foreground">La source ne fournit pas de description : consultez l&rsquo;annonce d&rsquo;origine.</p>
              )}
            </CardContent>
          </Card>

          <Card className="gap-0 py-0">
            <CardHeader className="border-b px-6 py-4">
              <CardTitle className="text-sm font-semibold">{o.source_links.length > 1 ? `Publiée sur ${o.source_links.length} sources` : "Source"}</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ul className="divide-y">
                {o.source_links.map((s) => {
                  const href = safeExternalUrl(s.original_url);
                  return (
                    <li key={`${s.source_key}-${s.original_url}`} className="flex flex-col gap-1.5 px-6 py-4 text-sm">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{s.source_name}</span>
                        {s.status !== "listed" && <Badge variant="warning">{s.status === "closed" ? "Clôturée sur cette source" : "Plus visible sur cette source"}</Badge>}
                        {href && (
                          <a href={href} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex items-center gap-1 text-xs underline underline-offset-4">
                            Ouvrir <ExternalLink className="size-3" aria-hidden="true" />
                            <span className="sr-only">(nouvel onglet)</span>
                          </a>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {s.published_at ? `Publiée le ${formatDate(s.published_at)}` : s.published_text ? `Affichée « ${s.published_text} » par la source` : "Date de publication inconnue"} · vue pour la première fois le{" "}
                        {formatDate(s.first_seen_at)}
                      </p>
                      {s.attribution && <p className="text-xs text-muted-foreground">{s.attribution}</p>}
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        </>
      }
      aside={
        <>
          <HighlightBar icon={Gauge} value={o.score == null ? DASH : `${Math.round(o.score)} / 100`} label={o.score_profile_name ? `profil « ${o.score_profile_name} »` : "score de pertinence"} />
          <TrackingCard offer={o} onChange={onChange} />
          <ScoresCard scores={o.scores} />
        </>
      }
    />
  );
}

function TrackingCard({ offer, onChange }: { offer: OfferDetail; onChange: (o: OfferDetail) => void }) {
  const toast = useToast();
  const [notes, setNotes] = useState(offer.notes ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const dirty = notes.trim() !== (offer.notes ?? "").trim();

  async function patch(body: { user_status?: UserStatus; notes?: string | null }, key: string, okMessage: string) {
    setBusy(key);
    try {
      const updated = await api.patch<OfferDetail>(`/offers/${offer.id}/status`, body);
      onChange(updated);
      setNotes(updated.notes ?? "");
      toast.success(okMessage);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Mon suivi</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div role="group" aria-label="Statut de suivi" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {STATUS_ACTIONS.map(({ value, icon: Icon }) => {
            const active = offer.user_status === value;
            return (
              <Button
                key={value}
                variant={active ? "default" : "outline"}
                size="sm"
                className="justify-start"
                aria-pressed={active}
                disabled={busy !== null}
                onClick={() => !active && patch({ user_status: value }, value, `Statut : ${USER_STATUS_LABELS[value].toLowerCase()}.`)}
              >
                {busy === value ? <Loader2 className="animate-spin" /> : <Icon />}
                {USER_STATUS_LABELS[value]}
              </Button>
            );
          })}
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="notes" className="text-[13px] font-medium">
            Notes personnelles
          </label>
          <Textarea id="notes" rows={4} maxLength={5000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Contact, échéance, impressions…" />
          <div>
            <Button size="sm" variant="secondary" disabled={!dirty || busy !== null} onClick={() => patch({ notes: notes.trim() || null }, "notes", "Notes enregistrées.")}>
              {busy === "notes" && <Loader2 className="animate-spin" />} Enregistrer les notes
            </Button>
          </div>
        </div>
        {offer.saved_at && <p className="text-xs text-muted-foreground">Sauvegardée le {formatDate(offer.saved_at)}.</p>}
      </CardContent>
    </Card>
  );
}

function ScoresCard({ scores }: { scores: OfferScore[] }) {
  if (!scores.length) {
    return (
      <Callout title="Aucun score">
        Aucun profil actif n&rsquo;a évalué cette offre. Activez un profil dans <Link href="/profiles" className="font-medium text-foreground underline underline-offset-4">Profils de recherche</Link>.
      </Callout>
    );
  }
  const sorted = [...scores].sort((a, b) => b.score - a.score);
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="border-b px-6 py-4">
        <CardTitle className="text-sm font-semibold">Pourquoi ce score ?</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        {sorted.map((s, i) => (
          <details key={s.profile_id} className="group border-b last:border-b-0" open={i === 0}>
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-6 py-4 text-sm outline-none focus-visible:bg-muted/50">
              <span className="min-w-0 truncate font-medium">{s.profile_name}</span>
              <span className="tabular-nums font-semibold">{Math.round(s.score)}/100</span>
            </summary>
            <div className="flex flex-col gap-4 px-6 pb-5">
              <ul className="flex flex-col gap-2.5">
                {Object.entries(s.breakdown).map(([key, c]) => (
                  <li key={key} className="text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span>{c.label}</span>
                      <span className="tabular-nums text-muted-foreground">{c.applicable ? `${c.points} / ${c.max}` : "non évalué"}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                      <div className="h-full rounded-full bg-chart-1" style={{ width: c.applicable && c.max > 0 ? `${(c.points / c.max) * 100}%` : "0%" }} />
                    </div>
                  </li>
                ))}
              </ul>
              {s.explanation.matched_keywords.length > 0 && <TagLine title="Mots-clés trouvés" items={s.explanation.matched_keywords} />}
              {s.explanation.excluded.length > 0 && <TagLine title="Mots exclus détectés" items={s.explanation.excluded} tone="destructive" />}
              {s.explanation.missing.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">Informations manquantes (comptées 0, jamais en positif) :</span> {s.explanation.missing.join(", ")}
                </p>
              )}
              {s.explanation.restrictions.length > 0 && <p className="text-xs text-warning">{s.explanation.restrictions.join(" · ")}</p>}
              {s.explanation.notes.map((n) => (
                <p key={n} className="text-xs text-muted-foreground">
                  {n}
                </p>
              ))}
              <p className="text-[11px] text-muted-foreground">Calculé le {formatDateTime(s.computed_at)}</p>
            </div>
          </details>
        ))}
      </CardContent>
    </Card>
  );
}

function TagLine({ title, items, tone }: { title: string; items: string[]; tone?: "destructive" }) {
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs font-medium">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((k) => (
          <Badge key={k} variant={tone === "destructive" ? "destructive" : "secondary"}>
            {k}
          </Badge>
        ))}
      </div>
    </div>
  );
}
