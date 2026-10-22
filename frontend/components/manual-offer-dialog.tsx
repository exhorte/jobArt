"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Plus } from "lucide-react";

import { Callout } from "@/components/callout";
import { Field } from "@/components/field";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, errorMessage } from "@/lib/api";
import { CONTRACT_LABELS, WORK_MODE_LABELS } from "@/lib/format";
import type { Meta, OfferDetail } from "@/lib/types";

const EMPTY = { url: "", title: "", company_name: "", location: "", description: "", contract_type: "", work_mode: "", notes: "" };

/**
 * Ajout manuel d'une annonce (LinkedIn, source bloquée, bouche-à-oreille…). Le serveur n'ouvre JAMAIS l'URL saisie :
 * il enregistre uniquement ce que vous renseignez ici.
 */
export function ManualOfferDialog({ meta }: { meta: Meta | undefined }) {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() === "" ? null : v.trim()]));
      const offer = await api.post<OfferDetail>("/offers/manual", body);
      toast.success("Annonce enregistrée.");
      setOpen(false);
      setForm(EMPTY);
      router.push(`/offers/${offer.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Plus /> Ajouter une annonce
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Ajouter une annonce manuellement</DialogTitle>
          <DialogDescription>Pour une offre vue ailleurs (LinkedIn, réseau, site non collecté). Elle est dédoublonnée et notée comme les autres.</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <Field id="m-url" label="Lien de l'annonce *" hint="L'adresse complète de la page d'origine (https://…). Elle n'est pas visitée par JobRadar.">
            <Input id="m-url" type="url" inputMode="url" value={form.url} onChange={set("url")} required placeholder="https://www.linkedin.com/jobs/view/…" autoFocus />
          </Field>
          <Field id="m-title" label="Intitulé du poste *">
            <Input id="m-title" value={form.title} onChange={set("title")} required maxLength={300} />
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="m-company" label="Entreprise">
              <Input id="m-company" value={form.company_name} onChange={set("company_name")} maxLength={300} />
            </Field>
            <Field id="m-location" label="Lieu" hint="Ex. Dakar, Sénégal">
              <Input id="m-location" value={form.location} onChange={set("location")} maxLength={300} />
            </Field>
            <Field id="m-contract" label="Contrat">
              <Select id="m-contract" value={form.contract_type} onChange={set("contract_type")}>
                <option value="">Non précisé</option>
                {(meta?.contract_types ?? Object.keys(CONTRACT_LABELS)).map((c) => (
                  <option key={c} value={c}>
                    {CONTRACT_LABELS[c] ?? c}
                  </option>
                ))}
              </Select>
            </Field>
            <Field id="m-mode" label="Mode de travail">
              <Select id="m-mode" value={form.work_mode} onChange={set("work_mode")}>
                <option value="">Non précisé</option>
                {(Object.keys(WORK_MODE_LABELS) as (keyof typeof WORK_MODE_LABELS)[]).map((m) => (
                  <option key={m} value={m}>
                    {WORK_MODE_LABELS[m]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Field id="m-description" label="Description" hint="Collez le texte de l'annonce : il sert au score (compétences, expérience…).">
            <Textarea id="m-description" value={form.description} onChange={set("description")} rows={5} maxLength={20000} />
          </Field>
          <Field id="m-notes" label="Notes personnelles">
            <Textarea id="m-notes" value={form.notes} onChange={set("notes")} rows={2} maxLength={5000} />
          </Field>
          {error && (
            <Callout title="Enregistrement impossible" variant="warning">
              {error}
            </Callout>
          )}
          <Button type="submit" size="lg" disabled={busy || !form.url.trim() || !form.title.trim()}>
            {busy && <Loader2 className="animate-spin" />} Enregistrer l&rsquo;annonce
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
