"use client";

import { useQuery } from "@tanstack/react-query";

import { AuditTable } from "@/features/audit/audit-table";
import { influencersApi, queryKeys } from "@/lib/api";

/** Per-entity history: the same audit data, pre-filtered to this influencer. */
export function InfluencerHistoryTab({ influencerId }: { influencerId: string }) {
  const query = useQuery({
    queryKey: queryKeys.influencerHistory(influencerId),
    queryFn: () => influencersApi.history(influencerId),
  });

  return (
    <div className="flex flex-col gap-3">
      <p className="text-fg-subtle text-sm">
        Every change to this character, newest first. Entries are append-only and ordered by a
        monotonic sequence, so actions taken within one request stay in the order they happened.
      </p>
      <AuditTable
        entries={query.data?.items}
        isLoading={query.isLoading}
        error={query.error}
        showEntityColumn={false}
        emptyMessage="Nothing recorded for this influencer yet."
      />
    </div>
  );
}
