"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Loader2, Plus, X } from "lucide-react";

import { Callout } from "@/components/callout";
import { Field } from "@/components/field";
import { TagInput } from "@/components/tag-input";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage } from "@/lib/api";
import { CONTRACT_LABELS, EXPERIENCE_LABELS, WORK_MODE_LABELS } from "@/lib/format";
import type { Meta, Profile, ProfileInput } from "@/lib/types";

interface GroupRow {
  uid: number;
  name: string;
  items: string[];
}

interface FormState {
  name: string;
  description: string;
  is_active: boolean;
  countries: string[];
  cities: string[];
  positive_keywords: string[];
  target_roles: string[];
  excluded_keywords: string[];
  groups: GroupRow[];
  sectors: string[];
  contract_types: string[];
  work_modes: string[];
  experience_levels: string[];
  weights: Record<string, string>; // vide = valeur par défaut
}

let uidCounter = 1;

function toForm(p: Profile | null): FormState {
  return {
    name: p?.name ?? "",
    description: p?.description ?? "",
    is_active: p?.is_active ?? true,
    countries: p?.countries ?? ["SN"],
    cities: p?.cities ?? [],
    positive_keywords: p?.positive_keywords ?? [],
    target_roles: p?.target_roles ?? [],
    excluded_keywords: p?.excluded_keywords ?? [],
    groups: Object.entries(p?.keyword_groups ?? {}).map(([name, items]) => ({ uid: uidCounter++, name, items })),
    sectors: p?.sectors ?? [],
    contract_types: p?.contract_types ?? [],
    work_modes: p?.work_modes ?? [],
    experience_levels: p?.experience_levels ?? [],
    weights: Object.fromEntries(Object.entries(p?.weights ?? {}).map(([k, v]) => [k, String(v)])),
  };
}

function toBody(f: FormState): ProfileInput {
  const weights = Object.fromEntries(Object.entries(f.weights).filter(([, v]) => v.trim() !== "").map(([k, v]) => [k, Number(v)]));
  return {
    name: f.name.trim(),
    description: f.description.trim() || null,
    is_active: f.is_active,
    countries: f.countries,
    cities: f.cities,
    positive_keywords: f.positive_keywords,
    target_roles: f.target_roles,
    excluded_keywords: f.excluded_keywords,
    keyword_groups: Object.fromEntries(f.groups.filter((g) => g.name.trim() && g.items.length).map((g) => [g.name.trim(), g.items])),
    sectors: f.sectors,
    contract_types: f.contract_types,
    work_modes: f.work_modes,
    experience_levels: f.experience_levels,
    weights: Object.keys(weights).length ? weights : null,
  };
}

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-4 rounded-xl border p-5">
      <legend className="px-2 text-sm font-semibold">{title}</legend>
      {description && <p className="-mt-2 text-xs text-muted-foreground">{description}</p>}
      {children}
    </fieldset>
  );
}

function CheckGrid({ legend, options, value, onChange }: { legend: string; options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-[13px] font-medium">{legend}</legend>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-foreground"
              checked={value.includes(o.value)}
              onChange={() => onChange(value.includes(o.value) ? value.filter((v) => v !== o.value) : [...value, o.value])}
            />
            <span className="truncate">{o.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Création / modification d'un profil de recherche (`profile = null` : création). */
export function ProfileDialog({
  open,
  onOpenChange,
  profile,
  meta,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  profile: Profile | null;
  meta: Meta | undefined;
  onSaved: () => Promise<void> | void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{profile ? `Modifier « ${profile.name} »` : "Nouveau profil de recherche"}</DialogTitle>
          <DialogDescription>
            Le profil pilote la recherche (mots-clés, pays) et le score de chaque offre. Les scores sont recalculés après chaque enregistrement.
          </DialogDescription>
        </DialogHeader>
        {open && <ProfileForm key={profile?.id ?? "new"} profile={profile} meta={meta} onClose={() => onOpenChange(false)} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}

function ProfileForm({ profile, meta, onClose, onSaved }: { profile: Profile | null; meta: Meta | undefined; onClose: () => void; onSaved: () => Promise<void> | void }) {
  const toast = useToast();
  const [f, setF] = useState<FormState>(() => toForm(profile));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((cur) => ({ ...cur, [k]: v }));

  const sectorLabels = Object.values(meta?.sectors ?? {});
  const sectorOptions = [...new Set([...sectorLabels, ...f.sectors])].map((s) => ({ value: s, label: s }));
  const weightKeys = Object.keys(meta?.weights.default ?? {});

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!f.name.trim()) {
      setError("Le nom du profil est obligatoire.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = toBody(f);
      if (profile) await api.patch(`/search-profiles/${profile.id}`, body);
      else await api.post("/search-profiles", body);
      toast.success(profile ? "Profil modifié : scores recalculés en arrière-plan." : "Profil créé : scores recalculés en arrière-plan.");
      await onSaved();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
      <Section title="Général">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field id="p-name" label="Nom du profil *">
            <Input id="p-name" value={f.name} onChange={(e) => set("name", e.target.value)} maxLength={120} required autoFocus />
          </Field>
          <label className="flex h-10 items-center gap-3 text-sm font-medium">
            <Switch checked={f.is_active} onCheckedChange={(v) => set("is_active", v)} aria-label="Profil actif" />
            Profil actif
          </label>
        </div>
        <Field id="p-desc" label="Description">
          <Textarea id="p-desc" rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} maxLength={2000} />
        </Field>
      </Section>

      <Section title="Géographie" description="La première ville est prioritaire pour le score de localisation.">
        <Field id="p-countries" label="Pays (codes ISO)" hint="Ex. SN, CI, ML. Un profil sans pays accepte toutes les sources.">
          <TagInput id="p-countries" label="pays" value={f.countries} onChange={(v) => set("countries", v)} transform={(s) => s.toUpperCase()} placeholder="SN" />
        </Field>
        <Field id="p-cities" label="Villes">
          <TagInput id="p-cities" label="villes" value={f.cities} onChange={(v) => set("cities", v)} placeholder="Dakar" />
        </Field>
      </Section>

      <Section title="Métier" description="L'ordre des mots-clés compte : les sources limitent le nombre de requêtes, les premiers sont cherchés d'abord.">
        <Field id="p-kw" label="Mots-clés recherchés" hint="Titres ou termes de poste (Entrée pour ajouter).">
          <TagInput id="p-kw" label="mots-clés" value={f.positive_keywords} onChange={(v) => set("positive_keywords", v)} placeholder="Software Engineer" />
        </Field>
        <Field id="p-roles" label="Métiers cibles" hint="Intitulés reconnus pour le score « métier ».">
          <TagInput id="p-roles" label="métiers cibles" value={f.target_roles} onChange={(v) => set("target_roles", v)} />
        </Field>
        <Field id="p-excl" label="Mots exclus" hint="Dans le titre : score à 0. Dans la description : −20 points.">
          <TagInput id="p-excl" label="mots exclus" value={f.excluded_keywords} onChange={(v) => set("excluded_keywords", v)} />
        </Field>
      </Section>

      <Section title="Compétences" description="Groupes de compétences utilisés pour le score. Ce sont des hypothèses à ajuster : JobRadar n'affirme rien sur vos compétences.">
        <div className="flex flex-col gap-4">
          {f.groups.map((g, i) => (
            <div key={g.uid} className="grid grid-cols-1 gap-3 rounded-lg border bg-muted/30 p-3 sm:grid-cols-[12rem_1fr_auto] sm:items-start">
              <Field id={`p-gname-${g.uid}`} label="Groupe">
                <Input
                  id={`p-gname-${g.uid}`}
                  value={g.name}
                  onChange={(e) => set("groups", f.groups.map((x) => (x.uid === g.uid ? { ...x, name: e.target.value } : x)))}
                  placeholder="Langages"
                />
              </Field>
              <Field id={`p-gitems-${g.uid}`} label="Compétences">
                <TagInput
                  id={`p-gitems-${g.uid}`}
                  label={`compétences du groupe ${g.name || i + 1}`}
                  value={g.items}
                  onChange={(v) => set("groups", f.groups.map((x) => (x.uid === g.uid ? { ...x, items: v } : x)))}
                  placeholder="Python"
                />
              </Field>
              <Button type="button" variant="ghost" size="icon" className="sm:mt-6" aria-label={`Supprimer le groupe ${g.name || i + 1}`} onClick={() => set("groups", f.groups.filter((x) => x.uid !== g.uid))}>
                <X />
              </Button>
            </div>
          ))}
          <div>
            <Button type="button" variant="outline" size="sm" onClick={() => set("groups", [...f.groups, { uid: uidCounter++, name: "", items: [] }])}>
              <Plus /> Ajouter un groupe
            </Button>
          </div>
        </div>
      </Section>

      <Section title="Critères de l'offre">
        <CheckGrid legend="Types de contrat" value={f.contract_types} onChange={(v) => set("contract_types", v)} options={(meta?.contract_types ?? Object.keys(CONTRACT_LABELS)).map((c) => ({ value: c, label: CONTRACT_LABELS[c] ?? c }))} />
        <CheckGrid legend="Modes de travail" value={f.work_modes} onChange={(v) => set("work_modes", v)} options={(Object.keys(WORK_MODE_LABELS) as (keyof typeof WORK_MODE_LABELS)[]).map((m) => ({ value: m, label: WORK_MODE_LABELS[m] }))} />
        <CheckGrid legend="Niveaux d'expérience" value={f.experience_levels} onChange={(v) => set("experience_levels", v)} options={(meta?.experience_levels ?? Object.keys(EXPERIENCE_LABELS)).map((l) => ({ value: l, label: EXPERIENCE_LABELS[l] ?? l }))} />
        {sectorOptions.length > 0 && <CheckGrid legend="Secteurs" value={f.sectors} onChange={(v) => set("sectors", v)} options={sectorOptions} />}
      </Section>

      <Section title="Pondération du score (facultatif)" description="Poids relatifs des six critères. Laissez vide pour la valeur par défaut ; 0 désactive un critère. Un critère sans information dans l'annonce vaut 0 point, jamais un point positif.">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {weightKeys.map((k) => (
            <Field key={k} id={`p-w-${k}`} label={meta?.weights.labels[k] ?? k}>
              <Input
                id={`p-w-${k}`}
                type="number"
                inputMode="decimal"
                min={0}
                max={100}
                step="any"
                placeholder={String(meta?.weights.default[k] ?? "")}
                value={f.weights[k] ?? ""}
                onChange={(e) => set("weights", { ...f.weights, [k]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </Section>

      {error && (
        <Callout title="Enregistrement impossible" variant="warning">
          <span className="break-words">{error}</span>
        </Callout>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose} disabled={busy}>
          Annuler
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Loader2 className="animate-spin" />} {profile ? "Enregistrer" : "Créer le profil"}
        </Button>
      </div>
    </form>
  );
}
