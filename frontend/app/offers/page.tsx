"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Briefcase, RotateCcw, Search } from "lucide-react";

import { ErrorNotice, PageSkeleton } from "@/components/async-state";
import { EmptyState } from "@/components/empty-state";
import { Field } from "@/components/field";
import { PageHeader } from "@/components/layout/page-header";
import { LaunchRunButton } from "@/components/launch-run-button";
import { ManualOfferDialog } from "@/components/manual-offer-dialog";
import { OffersTable } from "@/components/offers-table";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useApi } from "@/lib/api";
import { CONTRACT_LABELS, USER_STATUS_LABELS, WORK_MODE_LABELS, formatNumber } from "@/lib/format";
import type { Meta, OfferPage, Profile, Source } from "@/lib/types";
import { useDebounced } from "@/lib/use-debounced";

const PAGE_SIZE = 25;

const DEFAULTS = {
  q: "",
  profile_id: "",
  source: "",
  country: "",
  city: "",
  company: "",
  contract_type: "",
  work_mode: "",
  status: "",
  min_score: "",
  published_from: "",
  first_seen_from: "",
  sort: "recent",
  order: "desc",
  include_ignored: "",
};
type Filters = typeof DEFAULTS;
type FilterKey = keyof Filters;

const SORTS: { value: string; label: string; order: "asc" | "desc" }[] = [
  { value: "recent", label: "Plus récentes (publication)", order: "desc" },
  { value: "relevance", label: "Plus pertinentes (score)", order: "desc" },
  { value: "detected", label: "Dernières détectées", order: "desc" },
  { value: "company", label: "Entreprise (A → Z)", order: "asc" },
];

function readFilters(sp: URLSearchParams): { filters: Filters; page: number } {
  const filters = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS) as FilterKey[]) {
    const v = sp.get(k);
    if (v) filters[k] = v;
  }
  const page = Math.max(1, parseInt(sp.get("page") ?? "1", 10) || 1);
  return { filters, page };
}

function buildQuery(f: Filters, page: number): URLSearchParams {
  const qs = new URLSearchParams();
  for (const k of Object.keys(DEFAULTS) as FilterKey[]) {
    if (f[k] && f[k] !== DEFAULTS[k]) qs.set(k, f[k]);
  }
  if (f.sort !== DEFAULTS.sort || f.order !== DEFAULTS.order) {
    qs.set("sort", f.sort);
    qs.set("order", f.order);
  }
  if (page > 1) qs.set("page", String(page));
  return qs;
}

export default function OffersPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <OffersView />
    </Suspense>
  );
}

function OffersView() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Filtres et page forment un seul état : la requête est retardée en bloc (pas de requête à chaque frappe, pas de page périmée).
  const [state, setState] = useState(() => readFilters(new URLSearchParams(searchParams.toString())));
  const { filters } = state;
  const effective = useDebounced(state, 300);

  const { data: meta } = useApi<Meta>("/meta");
  const { data: sources } = useApi<Source[]>("/sources");
  const { data: profiles } = useApi<Profile[]>("/search-profiles");

  const query = useMemo(() => buildQuery(effective.filters, effective.page), [effective]);
  const apiQuery = useMemo(() => {
    const qs = new URLSearchParams(query);
    if (qs.has("published_from")) qs.set("published_from", `${qs.get("published_from")}T00:00:00Z`);
    if (qs.has("first_seen_from")) qs.set("first_seen_from", `${qs.get("first_seen_from")}T00:00:00Z`);
    if (qs.has("include_ignored")) qs.set("include_ignored", "true");
    qs.set("page", String(effective.page));
    qs.set("page_size", String(PAGE_SIZE));
    return qs.toString();
  }, [query, effective.page]);

  useEffect(() => {
    const qs = query.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [query, pathname, router]);

  const { data, error, reload, fetching } = useApi<OfferPage>(`/offers?${apiQuery}`);

  const update = (patch: Partial<Filters>) => setState((cur) => ({ filters: { ...cur.filters, ...patch }, page: 1 }));
  const reset = () => setState({ filters: { ...DEFAULTS }, page: 1 });
  const set = (k: FilterKey) => (e: { target: { value: string } }) => update({ [k]: e.target.value });
  const activeCount = (Object.keys(DEFAULTS) as FilterKey[]).filter((k) => !["sort", "order", "q"].includes(k) && filters[k] && filters[k] !== DEFAULTS[k]).length;
  const anyFilter = activeCount > 0 || filters.q !== "";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Offres"
        icon={Briefcase}
        subtitle={data ? `${formatNumber(data.total)} offre(s) ${anyFilter ? "correspondant aux filtres" : "uniques"}` : "Chargement…"}
        actions={<ManualOfferDialog meta={meta} />}
      />

      <Card className="gap-4 p-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_16rem]">
          <Field id="f-q" label="Mots-clés" hint="Dans le titre, l'entreprise et la description.">
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input id="f-q" type="search" className="pl-9" value={filters.q} onChange={set("q")} placeholder="Ex. Python, data, comptable…" />
            </div>
          </Field>
          <Field id="f-sort" label="Trier par">
            <Select
              id="f-sort"
              value={filters.sort}
              onChange={(e) => {
                const s = SORTS.find((x) => x.value === e.target.value)!;
                update({ sort: s.value, order: s.order });
              }}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <details className="group" open={activeCount > 0}>
          <summary className="flex w-fit cursor-pointer list-none items-center gap-2 rounded-md text-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40">
            <span className="underline underline-offset-4">Filtres avancés</span>
            {activeCount > 0 && <span className="rounded-full bg-primary px-2 py-0.5 text-[11px] text-primary-foreground tabular-nums">{activeCount}</span>}
          </summary>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field id="f-profile" label="Profil de recherche" hint="Affiche le score de ce profil.">
              <Select id="f-profile" value={filters.profile_id} onChange={set("profile_id")}>
                <option value="">Meilleur score tous profils</option>
                {profiles?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.is_active ? "" : " (inactif)"}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="f-source" label="Source">
              <Select id="f-source" value={filters.source} onChange={set("source")}>
                <option value="">Toutes</option>
                {sources
                  ?.filter((s) => s.offers_count > 0 || s.can_collect)
                  .map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.name} ({s.offers_count})
                    </option>
                  ))}
              </Select>
            </Field>
            <Field id="f-country" label="Pays">
              <Select id="f-country" value={filters.country} onChange={set("country")}>
                <option value="">Tous</option>
                {Object.entries(meta?.countries ?? {}).map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="f-city" label="Ville">
              <Input id="f-city" value={filters.city} onChange={set("city")} placeholder="Ex. Dakar" />
            </Field>
            <Field id="f-company" label="Entreprise">
              <Input id="f-company" value={filters.company} onChange={set("company")} />
            </Field>
            <Field id="f-contract" label="Contrat">
              <Select id="f-contract" value={filters.contract_type} onChange={set("contract_type")}>
                <option value="">Tous</option>
                {(meta?.contract_types ?? Object.keys(CONTRACT_LABELS)).map((c) => (
                  <option key={c} value={c}>
                    {CONTRACT_LABELS[c] ?? c}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="f-mode" label="Mode de travail">
              <Select id="f-mode" value={filters.work_mode} onChange={set("work_mode")}>
                <option value="">Tous</option>
                {(Object.keys(WORK_MODE_LABELS) as (keyof typeof WORK_MODE_LABELS)[]).map((m) => (
                  <option key={m} value={m}>
                    {WORK_MODE_LABELS[m]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="f-status" label="Statut de suivi">
              <Select id="f-status" value={filters.status} onChange={set("status")}>
                <option value="">Tous (hors ignorées)</option>
                {(Object.keys(USER_STATUS_LABELS) as (keyof typeof USER_STATUS_LABELS)[]).map((s) => (
                  <option key={s} value={s}>
                    {USER_STATUS_LABELS[s]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="f-score" label="Score minimum" hint="0 à 100">
              <Input id="f-score" type="number" inputMode="numeric" min={0} max={100} value={filters.min_score} onChange={set("min_score")} />
            </Field>
            <Field id="f-pub" label="Publiée depuis le" hint="Date déclarée par la source">
              <Input id="f-pub" type="date" value={filters.published_from} onChange={set("published_from")} />
            </Field>
            <Field id="f-seen" label="Détectée depuis le" hint="Première détection par jobArt">
              <Input id="f-seen" type="date" value={filters.first_seen_from} onChange={set("first_seen_from")} />
            </Field>
            <div className="flex items-end">
              <label className="flex h-10 cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 accent-foreground"
                  checked={filters.include_ignored === "1"}
                  onChange={(e) => update({ include_ignored: e.target.checked ? "1" : "" })}
                />
                Afficher les offres ignorées
              </label>
            </div>
          </div>
        </details>

        {anyFilter && (
          <div>
            <Button variant="ghost" size="sm" onClick={reset}>
              <RotateCcw /> Réinitialiser les filtres
            </Button>
          </div>
        )}
      </Card>

      {error && !data && <ErrorNotice message={error} onRetry={reload} />}
      {!data && !error && <PageSkeleton rows={4} />}
      {data && (
        <>
          {error && <ErrorNotice message={`Actualisation impossible : ${error}`} onRetry={reload} />}
          {data.items.length === 0 ? (
            anyFilter ? (
              <EmptyState
                icon={Search}
                action={
                  <Button variant="outline" size="lg" onClick={reset}>
                    Réinitialiser les filtres
                  </Button>
                }
                hint="Aucune offre ne correspond à ces critères."
              />
            ) : (
              <EmptyState icon={Briefcase} action={<LaunchRunButton variant="outline" size="lg" />} hint="Aucune offre enregistrée : lancez une collecte ou ajoutez une annonce manuellement." />
            )
          ) : (
            <div className={fetching ? "flex flex-col gap-6 opacity-60 transition-opacity" : "flex flex-col gap-6 transition-opacity"} aria-busy={fetching}>
              <OffersTable offers={data.items} />
              <Pagination
                page={data.page}
                pageSize={data.page_size}
                total={data.total}
                onPage={(p) => {
                  setState((cur) => ({ ...cur, page: p }));
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
