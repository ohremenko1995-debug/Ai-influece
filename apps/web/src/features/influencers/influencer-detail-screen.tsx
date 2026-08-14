"use client";

import { ErrorNotice, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "@influenceros/ui";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

import { PageHeader } from "@/components/app-shell";
import { InfluencerStatusBadge } from "@/components/status-badge";
import { CharacterBibleTab } from "@/features/influencers/character-bible-tab";
import { InfluencerHistoryTab } from "@/features/influencers/influencer-history-tab";
import { InfluencerPoliciesTab } from "@/features/influencers/influencer-policies-tab";
import { InfluencerProfileTab } from "@/features/influencers/influencer-profile-tab";
import { InfluencerStatusActions } from "@/features/influencers/influencer-status-actions";
import { useSession } from "@/hooks/use-session";
import { influencersApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { PERMISSIONS, can } from "@/lib/permissions";

/**
 * Influencer detail.
 *
 * Tabs present today cover what the backend implements. `Visual DNA`, `Voice`,
 * `Assets`, `Content` and `Recipes` appear with their features rather than as empty
 * shells — an empty tab reads as a bug, not as a roadmap.
 */
export function InfluencerDetailScreen({ influencerId }: { influencerId: string }) {
  const { me } = useSession();
  const mayReadAudit = can(me, PERMISSIONS.auditRead);

  const query = useQuery({
    queryKey: queryKeys.influencer(influencerId),
    queryFn: () => influencersApi.read(influencerId),
  });

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4 px-6 py-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (query.error || !query.data) {
    return (
      <div className="px-6 py-6">
        <ErrorNotice
          title="Could not load this influencer"
          message={describeError(query.error)}
          requestId={requestIdOf(query.error)}
        />
      </div>
    );
  }

  const influencer = query.data;
  const blockers = influencer.activation_blockers;

  return (
    <div className="flex flex-col">
      <PageHeader
        title={influencer.public_name}
        description={`Code ${influencer.code} · ${influencer.primary_market} · ${influencer.primary_language}`}
        actions={
          <div className="flex items-center gap-3">
            <InfluencerStatusBadge status={influencer.status} />
            <InfluencerStatusActions influencer={influencer} />
          </div>
        }
      />

      <div className="flex flex-col gap-4 px-6 py-6">
        {blockers.length > 0 && influencer.status !== "archived" ? (
          <div
            className="border-warning-border bg-warning-bg flex flex-col gap-2 rounded-lg border px-4 py-3"
            role="status"
          >
            <div className="flex items-center gap-2">
              <AlertTriangle className="text-warning-fg size-4" aria-hidden />
              <p className="text-warning-fg text-sm font-medium">Cannot be activated yet</p>
            </div>
            <ul className="text-fg-muted ml-6 list-disc text-sm">
              {blockers.map((blocker) => (
                <li key={blocker}>{blocker}</li>
              ))}
            </ul>
          </div>
        ) : null}

        <Tabs defaultValue="profile">
          <TabsList>
            <TabsTrigger value="profile">Profile</TabsTrigger>
            <TabsTrigger value="bible">Character Bible</TabsTrigger>
            <TabsTrigger value="policies">Policies</TabsTrigger>
            {mayReadAudit ? <TabsTrigger value="history">History</TabsTrigger> : null}
          </TabsList>

          <TabsContent value="profile">
            <InfluencerProfileTab influencer={influencer} />
          </TabsContent>
          <TabsContent value="bible">
            <CharacterBibleTab influencer={influencer} />
          </TabsContent>
          <TabsContent value="policies">
            <InfluencerPoliciesTab influencer={influencer} />
          </TabsContent>
          {mayReadAudit ? (
            <TabsContent value="history">
              <InfluencerHistoryTab influencerId={influencer.id} />
            </TabsContent>
          ) : null}
        </Tabs>
      </div>
    </div>
  );
}
