import { StatusBadge, type StatusTone } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { CONTRACT_LABELS, FRESHNESS_LABELS, LIFECYCLE_LABELS, USER_STATUS_LABELS, WORK_MODE_LABELS, label } from "@/lib/format";
import type { LifecycleStatus, OfferListItem, UserStatus } from "@/lib/types";

const USER_TONE: Record<UserStatus, StatusTone> = { new: "neutral", seen: "neutral", saved: "success", applied: "success", ignored: "neutral" };

export function UserStatusBadge({ status }: { status: UserStatus }) {
  return <StatusBadge tone={USER_TONE[status]} label={USER_STATUS_LABELS[status]} />;
}

const LIFECYCLE_TONE: Record<LifecycleStatus, StatusTone> = { listed: "success", stale: "warning", deadline_passed: "warning", closed: "destructive" };

export function LifecycleBadge({ status }: { status: LifecycleStatus }) {
  return <StatusBadge tone={LIFECYCLE_TONE[status]} label={LIFECYCLE_LABELS[status]} />;
}

/** Fraîcheur : calculée UNIQUEMENT sur la date de publication déclarée par la source ; sinon « Date inconnue ». */
export function FreshnessBadge({ freshness }: { freshness: OfferListItem["freshness"] }) {
  const tone: StatusTone = freshness.label === "fresh" ? "success" : freshness.label === "old" ? "warning" : "neutral";
  const text = freshness.age_days != null ? `${FRESHNESS_LABELS[freshness.label]} · ${freshness.age_days} j` : FRESHNESS_LABELS[freshness.label];
  return <StatusBadge tone={tone} label={text} />;
}

export function ContractBadge({ value }: { value: string | null }) {
  return value ? <Badge variant="outline">{label(CONTRACT_LABELS, value)}</Badge> : null;
}

export function WorkModeBadge({ value }: { value: OfferListItem["work_mode"] }) {
  return value ? <Badge variant="outline">{WORK_MODE_LABELS[value]}</Badge> : null;
}
