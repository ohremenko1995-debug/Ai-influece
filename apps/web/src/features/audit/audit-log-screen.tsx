"use client";

import { ACTOR_TYPES } from "@influenceros/types";
import { Button, EmptyState, Input, Select } from "@influenceros/ui";
import { useQuery } from "@tanstack/react-query";
import { ShieldOff } from "lucide-react";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { AuditTable } from "@/features/audit/audit-table";
import { useSession } from "@/hooks/use-session";
import { auditApi, queryKeys } from "@/lib/api";
import { PERMISSIONS, can } from "@/lib/permissions";

const PAGE_SIZE = 50;

const ENTITY_TYPES = [
  "Influencer",
  "InfluencerVersion",
  "DisclosurePolicy",
  "Organization",
  "Membership",
  "User",
] as const;

export function AuditLogScreen() {
  const { me } = useSession();
  const mayRead = can(me, PERMISSIONS.auditRead);

  const [entityType, setEntityType] = useState("");
  const [actorType, setActorType] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);

  const params = useMemo(
    () => ({
      entityType: entityType || undefined,
      actorType: actorType || undefined,
      action: action.trim() || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [entityType, actorType, action, page],
  );

  const query = useQuery({
    queryKey: queryKeys.auditLogs(params),
    queryFn: () => auditApi.list(params),
    enabled: mayRead,
  });

  if (!mayRead) {
    return (
      <div className="flex flex-col">
        <PageHeader title="Audit log" />
        <div className="px-6 py-6">
          <EmptyState
            icon={<ShieldOff className="size-6" />}
            title="Your role cannot read the audit trail"
            description="Owner, creative lead, reviewer, compliance and analyst roles have audit access."
          />
        </div>
      </div>
    );
  }

  const total = query.data?.total ?? 0;
  const hasNextPage = (page + 1) * PAGE_SIZE < total;

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Audit log"
        description="Append-only record of every consequential change in this organization."
      />

      <div className="flex flex-col gap-4 px-6 py-6">
        <div className="flex flex-wrap items-end gap-3">
          <FilterSelect
            id="audit-entity"
            label="Entity type"
            value={entityType}
            onChange={(value) => {
              setEntityType(value);
              setPage(0);
            }}
            options={ENTITY_TYPES.map((value) => ({ value, label: value }))}
            allLabel="All entities"
          />
          <FilterSelect
            id="audit-actor"
            label="Actor type"
            value={actorType}
            onChange={(value) => {
              setActorType(value);
              setPage(0);
            }}
            options={ACTOR_TYPES.map((value) => ({ value, label: value }))}
            allLabel="All actors"
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="audit-action" className="text-fg-muted text-xs font-medium">
              Action
            </label>
            <Input
              id="audit-action"
              value={action}
              onChange={(event) => {
                setAction(event.target.value);
                setPage(0);
              }}
              placeholder="influencer.created"
              className="w-56 font-mono text-xs"
            />
          </div>
          <p className="text-fg-subtle pb-2.5 text-xs">
            {total} {total === 1 ? "entry" : "entries"}
          </p>
        </div>

        <AuditTable entries={query.data?.items} isLoading={query.isLoading} error={query.error} />

        {total > PAGE_SIZE ? (
          <div className="flex items-center justify-between">
            <p className="text-fg-subtle text-xs tabular-nums">
              {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
            </p>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                disabled={page === 0}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => setPage((current) => current + 1)}
                disabled={!hasNextPage}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function FilterSelect({
  id,
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
  allLabel: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-fg-muted text-xs font-medium">
        {label}
      </label>
      <Select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-44"
      >
        <option value="">{allLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
    </div>
  );
}
