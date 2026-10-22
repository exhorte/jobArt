"use client";

import { useState } from "react";
import { Copy, Loader2, Pencil, Plus, Target, Trash2 } from "lucide-react";

import { Loadable } from "@/components/async-state";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { ProfileDialog } from "@/components/profile-dialog";
import { StatusBadge } from "@/components/status-badge";
import { useToast } from "@/components/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { ApiError, api, errorMessage, useApi } from "@/lib/api";
import { CONTRACT_LABELS, EXPERIENCE_LABELS, WORK_MODE_LABELS, formatDate, label } from "@/lib/format";
import type { Meta, Profile, WorkMode } from "@/lib/types";

export default function ProfilesPage() {
  const toast = useToast();
  const { data, error, reload } = useApi<Profile[]>("/search-profiles");
  const { data: meta } = useApi<Meta>("/meta");
  const [editing, setEditing] = useState<Profile | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Profile | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function act(key: string, fn: () => Promise<void>) {
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const toggle = (p: Profile, active: boolean) =>
    act(`t${p.id}`, async () => {
      await api.patch(`/search-profiles/${p.id}`, { is_active: active });
      toast.success(`« ${p.name} » ${active ? "activé" : "désactivé"} : scores recalculés en arrière-plan.`);
      await reload();
    });

  const duplicate = (p: Profile) =>
    act(`d${p.id}`, async () => {
      const copy = await api.post<Profile>(`/search-profiles/${p.id}/duplicate`);
      toast.success(`Copie créée : « ${copy.name} » (désactivée jusqu'à vérification).`);
      await reload();
    });

  const remove = (p: Profile) =>
    act(`x${p.id}`, async () => {
      await api.delete(`/search-profiles/${p.id}`);
      toast.success(`« ${p.name} » supprimé.`);
      setDeleting(null);
      await reload();
    });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Profils de recherche"
        icon={Target}
        subtitle={data ? `${data.filter((p) => p.is_active).length} actif(s) sur ${data.length}` : "Chargement…"}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> Nouveau profil
          </Button>
        }
      />

      <Loadable error={error} hasData={!!data} onRetry={reload} rows={3}>
        {data && data.length === 0 ? (
          <EmptyState icon={Target} action={<Button variant="outline" size="lg" onClick={() => setCreating(true)}>Créer un profil</Button>} hint="Sans profil actif, les offres sont collectées mais aucun score n'est calculé." />
        ) : (
          <div className="flex flex-col gap-4">
            {data?.map((p) => (
              <ProfileCard key={p.id} p={p} busy={busy} onToggle={toggle} onEdit={() => setEditing(p)} onDuplicate={() => duplicate(p)} onDelete={() => setDeleting(p)} />
            ))}
          </div>
        )}
      </Loadable>

      <ProfileDialog open={creating} onOpenChange={setCreating} profile={null} meta={meta} onSaved={reload} />
      <ProfileDialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)} profile={editing} meta={meta} onSaved={reload} />

      <Dialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Supprimer « {deleting?.name} » ?</DialogTitle>
            <DialogDescription>Les scores calculés pour ce profil sont supprimés. Les offres, elles, sont conservées. Cette action est définitive.</DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:justify-end">
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Annuler
            </Button>
            <Button variant="destructive" disabled={busy !== null} onClick={() => deleting && remove(deleting)}>
              {busy?.startsWith("x") && <Loader2 className="animate-spin" />} Supprimer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Chips({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <span className="text-xs text-muted-foreground">{empty}</span>;
  const shown = items.slice(0, 6);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((i) => (
        <Badge key={i} variant="secondary">
          {i}
        </Badge>
      ))}
      {items.length > shown.length && <Badge variant="outline">+{items.length - shown.length}</Badge>}
    </div>
  );
}

function Line({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 sm:grid-cols-[9rem_1fr] sm:gap-3">
      <dt className="text-xs text-muted-foreground sm:pt-0.5">{term}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  );
}

function ProfileCard({
  p,
  busy,
  onToggle,
  onEdit,
  onDuplicate,
  onDelete,
}: {
  p: Profile;
  busy: string | null;
  onToggle: (p: Profile, active: boolean) => void;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const groups = Object.entries(p.keyword_groups);
  return (
    <Card className="gap-0 py-0">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
        <div className="min-w-0">
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            <span className="break-words">{p.name}</span>
            <StatusBadge tone={p.is_active ? "success" : "neutral"} label={p.is_active ? "Actif" : "Inactif"} />
          </CardTitle>
          {p.description && <p className="mt-1.5 text-sm text-muted-foreground">{p.description}</p>}
        </div>
        <label className="inline-flex items-center gap-2 text-sm">
          <Switch checked={p.is_active} disabled={busy !== null} onCheckedChange={(v) => onToggle(p, v)} aria-label={`${p.is_active ? "Désactiver" : "Activer"} le profil ${p.name}`} />
          <span className="max-sm:sr-only">{p.is_active ? "Activé" : "Désactivé"}</span>
        </label>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-6 py-5">
        <dl className="flex flex-col gap-3">
          <Line term="Lieux">
            <Chips items={[...p.countries, ...p.cities]} empty="Tous pays" />
          </Line>
          <Line term="Mots-clés">
            <Chips items={p.positive_keywords} empty="Aucun mot-clé : le profil ne déclenche aucune requête" />
          </Line>
          <Line term="Compétences">
            {groups.length ? <Chips items={groups.flatMap(([, items]) => items)} empty="" /> : <span className="text-xs text-muted-foreground">Aucun groupe : critère « compétences » non évalué</span>}
          </Line>
          <Line term="Contrat · mode">
            <Chips items={[...p.contract_types.map((c) => label(CONTRACT_LABELS, c)), ...p.work_modes.map((m) => WORK_MODE_LABELS[m as WorkMode] ?? m)]} empty="Indifférent" />
          </Line>
          <Line term="Expérience">
            <Chips items={p.experience_levels.map((l) => label(EXPERIENCE_LABELS, l))} empty="Indifférent" />
          </Line>
          {p.excluded_keywords.length > 0 && (
            <Line term="Exclusions">
              <Chips items={p.excluded_keywords} empty="" />
            </Line>
          )}
        </dl>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <p className="text-xs text-muted-foreground">Modifié le {formatDate(p.updated_at)}</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={onEdit}>
              <Pencil /> Modifier
            </Button>
            <Button variant="outline" size="sm" disabled={busy !== null} onClick={onDuplicate}>
              {busy === `d${p.id}` ? <Loader2 className="animate-spin" /> : <Copy />} Dupliquer
            </Button>
            <Button variant="ghost" size="sm" onClick={onDelete} className="text-destructive hover:text-destructive">
              <Trash2 /> Supprimer
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
