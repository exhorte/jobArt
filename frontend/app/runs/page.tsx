"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { History } from "lucide-react";

import { ErrorNotice, Loadable, PageSkeleton } from "@/components/async-state";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { LaunchRunButton } from "@/components/launch-run-button";
import { Pagination } from "@/components/pagination";
import { RunCard, isActive } from "@/components/run-card";
import { useApi } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import type { Run, RunPage } from "@/lib/types";

const PAGE_SIZE = 15;

export default function RunsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <RunsView />
    </Suspense>
  );
}

function RunsView() {
  const searchParams = useSearchParams();
  const pinned = /^\d+$/.test(searchParams.get("run") ?? "") ? searchParams.get("run") : null;
  const [page, setPage] = useState(1);

  // Cadence adaptative : 3 s tant qu'une exécution est en cours (suivi en direct), 30 s sinon.
  const cadence = (d: unknown) => ((d as RunPage | undefined)?.items.some((r) => isActive(r.status)) ? 3_000 : 30_000);
  const { data, error, reload } = useApi<RunPage>(`/search-runs?page=${page}&page_size=${PAGE_SIZE}`, { refreshMs: cadence });
  const pinnedApi = useApi<Run>(pinned ? `/search-runs/${pinned}` : null, { refreshMs: (d) => ((d as Run | undefined) && isActive((d as Run).status) ? 3_000 : false) });

  const pinnedRun = pinnedApi.data && String(pinnedApi.data.id) === pinned ? pinnedApi.data : null;
  const rows = data?.items.filter((r) => r.id !== pinnedRun?.id) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Historique des collectes"
        icon={History}
        subtitle={data ? `${formatNumber(data.total)} exécution(s) enregistrée(s)` : "Chargement…"}
        actions={<LaunchRunButton variant="outline" />}
      />

      {pinned && pinnedApi.error && !pinnedRun && <ErrorNotice message={`Exécution n° ${pinned} : ${pinnedApi.error}`} />}
      {pinnedRun && <RunCard run={pinnedRun} defaultOpen highlighted />}

      <Loadable error={error} hasData={!!data} onRetry={reload} rows={4}>
        {data && data.total === 0 && !pinnedRun ? (
          <EmptyState icon={History} action={<LaunchRunButton variant="outline" size="lg" />} hint="Aucune collecte n'a encore été lancée." />
        ) : (
          data && (
            <>
              <div className="flex flex-col gap-3">
                {rows.map((r) => (
                  <RunCard key={r.id} run={r} />
                ))}
              </div>
              <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />
            </>
          )
        )}
      </Loadable>
    </div>
  );
}
