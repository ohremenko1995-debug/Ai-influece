"use client";

import type { InfluencerStatus } from "@influenceros/types";
import { INFLUENCER_STATUSES } from "@influenceros/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ErrorNotice,
  Skeleton,
} from "@influenceros/ui";
import { useQuery } from "@tanstack/react-query";
import { ScrollText, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/app-shell";
import { ActorTypeBadge } from "@/components/status-badge";
import { useSession } from "@/hooks/use-session";
import { auditApi, influencersApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { formatRelative, humaniseAction } from "@/lib/format";
import { PERMISSIONS, can } from "@/lib/permissions";

/**
 * Operational overview.
 *
 * Deliberately narrow: it reports only what the implemented backend can answer.
 * Job throughput, QA pass rate and approval queue depth arrive with their features
 * rather than as placeholder tiles that imply data exists.
 */
export function OverviewDashboard() {
  const { me } = useSession();
  const mayReadAudit = can(me, PERMISSIONS.auditRead);

  const influencers = useQuery({
    queryKey: queryKeys.influencers({ includeArchived: true, limit: 200 }),
    queryFn: () => influencersApi.list({ includeArchived: true, limit: 200 }),
  });

  const recentActivity = useQuery({
    queryKey: queryKeys.auditLogs({ limit: 8 }),
    queryFn: () => auditApi.list({ limit: 8 }),
    enabled: mayReadAudit,
  });

  const counts = countByStatus(influencers.data?.items ?? []);
  const readyToProduce = counts.active;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Overview"
        description="Current state of the influencer roster and recent activity."
      />

      <div className="flex flex-col gap-6 px-6 py-6">
        {influencers.error ? (
          <ErrorNotice
            message={describeError(influencers.error)}
            requestId={requestIdOf(influencers.error)}
          />
        ) : null}

        <section aria-labelledby="roster-heading" className="flex flex-col gap-3">
          <h2 id="roster-heading" className="text-fg-muted text-sm font-medium">
            Influencer roster
          </h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {INFLUENCER_STATUSES.map((status) => (
              <StatTile
                key={status}
                label={statusLabel(status)}
                value={influencers.isLoading ? null : counts[status]}
                href={`/influencers?status=${status}`}
              />
            ))}
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="text-accent size-4" aria-hidden />
                Production readiness
              </CardTitle>
              <CardDescription>
                A character is production-ready once it is active — which requires an
                adult-representation confirmation, a disclosure policy and a Character Bible.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {influencers.isLoading ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                <p className="text-2xl font-semibold tabular-nums">
                  {readyToProduce}
                  <span className="text-fg-subtle pl-1.5 text-sm font-normal">
                    of {counts.total}
                  </span>
                </p>
              )}
              {counts.draft > 0 ? (
                <Link
                  href="/influencers?status=draft"
                  className="text-accent text-xs hover:underline"
                >
                  {counts.draft} still in draft
                </Link>
              ) : null}
            </CardContent>
          </Card>

          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ScrollText className="text-accent size-4" aria-hidden />
                Recent activity
              </CardTitle>
              <CardDescription>
                {mayReadAudit
                  ? "The newest audit entries for this organization."
                  : "Your role cannot read the audit trail."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!mayReadAudit ? (
                <p className="text-fg-subtle text-sm">Nothing to show.</p>
              ) : recentActivity.isLoading ? (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-4/5" />
                  <Skeleton className="h-5 w-3/5" />
                </div>
              ) : recentActivity.data && recentActivity.data.items.length > 0 ? (
                <ul className="divide-border flex flex-col divide-y">
                  {recentActivity.data.items.map(({ entry }) => (
                    <li
                      key={entry.id}
                      className="flex items-center justify-between gap-3 py-2 text-sm"
                    >
                      <span className="min-w-0 truncate">
                        <span className="text-fg">{humaniseAction(entry.action)}</span>
                        <span className="text-fg-subtle pl-2 text-xs">{entry.entity_type}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2">
                        <ActorTypeBadge actorType={entry.actor_type} />
                        <time
                          dateTime={entry.created_at}
                          className="text-fg-subtle text-xs tabular-nums"
                        >
                          {formatRelative(entry.created_at)}
                        </time>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-fg-subtle text-sm">No activity recorded yet.</p>
              )}
            </CardContent>
          </Card>
        </section>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="text-accent size-4" aria-hidden />
              Not yet available
            </CardTitle>
            <CardDescription>
              Job throughput, QA pass rate and approval queue depth appear once those features land.
              They are listed here rather than shown as empty tiles, which would imply the data
              exists.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    </div>
  );
}

function StatTile({ label, value, href }: { label: string; value: number | null; href: string }) {
  return (
    <Link
      href={href}
      className="border-border bg-surface-1 hover:border-accent/50 hover:bg-surface-2 rounded-lg border px-4 py-3 transition-colors"
    >
      <p className="text-fg-subtle text-xs uppercase tracking-wide">{label}</p>
      {value === null ? (
        <Skeleton className="mt-1.5 h-7 w-10" />
      ) : (
        <p className="text-fg mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      )}
    </Link>
  );
}

function statusLabel(status: InfluencerStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function countByStatus(
  items: readonly { status: InfluencerStatus }[],
): Record<InfluencerStatus, number> & { total: number } {
  const counts = { draft: 0, active: 0, paused: 0, archived: 0, total: items.length };
  for (const item of items) counts[item.status] += 1;
  return counts;
}
