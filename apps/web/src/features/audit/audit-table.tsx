"use client";

import type { AuditLogDiff } from "@influenceros/types";
import {
  EmptyState,
  ErrorNotice,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableWrapper,
} from "@influenceros/ui";
import { ScrollText } from "lucide-react";

import { ActorTypeBadge } from "@/components/status-badge";
import { describeError, requestIdOf } from "@/lib/api-client";
import { formatDateTime, formatFieldValue, formatRelative, humaniseAction } from "@/lib/format";

export interface AuditTableProps {
  entries: AuditLogDiff[] | undefined;
  isLoading: boolean;
  error: unknown;
  /** Hidden when the table is already scoped to one entity. */
  showEntityColumn?: boolean;
  emptyMessage?: string;
}

/**
 * Audit entries with their computed field-level diffs.
 *
 * The diff is what makes an entry useful: "influencer.updated" alone says nothing,
 * whereas "public_name: Nora → Nora Prime" answers the question being asked.
 * Creations have no diff by design — the backend omits it rather than reporting
 * every column as changed from nothing.
 */
export function AuditTable({
  entries,
  isLoading,
  error,
  showEntityColumn = true,
  emptyMessage = "No activity recorded yet.",
}: AuditTableProps) {
  if (error) {
    return <ErrorNotice message={describeError(error)} requestId={requestIdOf(error)} />;
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2, 3, 4].map((row) => (
          <Skeleton key={row} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (!entries || entries.length === 0) {
    return <EmptyState icon={<ScrollText className="size-6" />} title={emptyMessage} />;
  }

  return (
    <TableWrapper>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-20">Seq</TableHead>
            <TableHead>Action</TableHead>
            {showEntityColumn ? <TableHead>Entity</TableHead> : null}
            <TableHead>Actor</TableHead>
            <TableHead>Changes</TableHead>
            <TableHead className="w-44">When</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {entries.map(({ entry, changed_fields }) => (
            <TableRow key={entry.id}>
              <TableCell className="text-fg-subtle font-mono text-xs tabular-nums">
                {entry.sequence_number}
              </TableCell>
              <TableCell className="whitespace-nowrap">{humaniseAction(entry.action)}</TableCell>
              {showEntityColumn ? (
                <TableCell>
                  <span className="text-fg-muted text-xs">{entry.entity_type}</span>
                </TableCell>
              ) : null}
              <TableCell>
                <ActorTypeBadge actorType={entry.actor_type} />
              </TableCell>
              <TableCell>
                <ChangeList changes={changed_fields} />
              </TableCell>
              <TableCell>
                {/* Relative for scanning, absolute in the tooltip for precision. */}
                <time
                  dateTime={entry.created_at}
                  title={formatDateTime(entry.created_at)}
                  className="text-fg-subtle whitespace-nowrap text-xs tabular-nums"
                >
                  {formatRelative(entry.created_at)}
                </time>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableWrapper>
  );
}

function ChangeList({ changes }: { changes: AuditLogDiff["changed_fields"] }) {
  const keys = Object.keys(changes);
  if (keys.length === 0) return <span className="text-fg-subtle text-xs">—</span>;

  return (
    <ul className="flex flex-col gap-0.5">
      {keys.map((key) => {
        const change = changes[key];
        return (
          <li key={key} className="font-mono text-xs">
            <span className="text-fg-muted">{key}</span>
            <span className="text-fg-subtle px-1">:</span>
            <span className="text-danger-fg line-through">{formatFieldValue(change?.from)}</span>
            <span className="text-fg-subtle px-1" aria-label="changed to">
              →
            </span>
            <span className="text-success-fg">{formatFieldValue(change?.to)}</span>
          </li>
        );
      })}
    </ul>
  );
}
