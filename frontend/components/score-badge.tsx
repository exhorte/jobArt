import { Badge } from "@/components/ui/badge";
import { formatScore, scoreTone } from "@/lib/format";

/** Score de pertinence /100 (calcul déterministe, jamais une promesse de recrutement). Absent → « — ». */
export function ScoreBadge({ score, className }: { score: number | null | undefined; className?: string }) {
  const tone = scoreTone(score);
  return (
    <Badge
      variant={tone === "success" ? "success" : tone === "warning" ? "warning" : "outline"}
      className={className}
      title={score == null ? "Aucun score : aucun profil actif" : `Score de pertinence : ${formatScore(score)} sur 100`}
    >
      <span className="tabular-nums">{formatScore(score)}</span>
      {score != null && <span className="font-normal opacity-70">/100</span>}
    </Badge>
  );
}
