"use client";

import type { InfluencerRead, InfluencerStatus } from "@influenceros/types";
import { INFLUENCER_STATUSES } from "@influenceros/types";
import {
  Button,
  EmptyState,
  ErrorNotice,
  Input,
  Select,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableWrapper,
} from "@influenceros/ui";
import { useQuery } from "@tanstack/react-query";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, Plus, Users } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { InfluencerStatusBadge } from "@/components/status-badge";
import { CreateInfluencerDialog } from "@/features/influencers/create-influencer-dialog";
import { useSession } from "@/hooks/use-session";
import { influencersApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { formatRelative } from "@/lib/format";
import { PERMISSIONS, can } from "@/lib/permissions";

const columnHelper = createColumnHelper<InfluencerRead>();

export function InfluencerListScreen() {
  const searchParams = useSearchParams();
  const { me } = useSession();
  const mayCreate = can(me, PERMISSIONS.influencerCreate);

  const statusFromUrl = searchParams.get("status");
  const [status, setStatus] = useState<InfluencerStatus | "all">(
    isInfluencerStatus(statusFromUrl) ? statusFromUrl : "all",
  );
  const [search, setSearch] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "created_at", desc: true }]);
  const [createOpen, setCreateOpen] = useState(false);

  const params = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      search: search.trim() || undefined,
      // "All statuses" must include archived, otherwise the filter lies.
      includeArchived: status === "all",
      limit: 100,
    }),
    [status, search],
  );

  const query = useQuery({
    queryKey: queryKeys.influencers(params),
    queryFn: () => influencersApi.list(params),
  });

  const columns = useMemo(
    () => [
      columnHelper.accessor("public_name", {
        header: "Name",
        cell: (info) => (
          <Link
            href={`/influencers/${info.row.original.id}`}
            className="text-fg hover:text-accent font-medium hover:underline"
          >
            {info.getValue()}
          </Link>
        ),
      }),
      columnHelper.accessor("code", {
        header: "Code",
        cell: (info) => <span className="text-fg-subtle font-mono text-xs">{info.getValue()}</span>,
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (info) => <InfluencerStatusBadge status={info.getValue()} />,
      }),
      columnHelper.accessor("niche", {
        header: "Niche",
        cell: (info) => info.getValue() ?? <span className="text-fg-subtle">—</span>,
      }),
      columnHelper.accessor("primary_market", {
        header: "Market",
        cell: (info) => (
          <span className="font-mono text-xs">
            {info.getValue()} · {info.row.original.primary_language}
          </span>
        ),
      }),
      columnHelper.accessor("adult_representation_confirmed", {
        header: "Adult confirmed",
        cell: (info) =>
          info.getValue() ? (
            <span className="text-success-fg">Yes</span>
          ) : (
            <span className="text-warning-fg">No</span>
          ),
      }),
      columnHelper.accessor("created_at", {
        header: "Created",
        cell: (info) => (
          <time dateTime={info.getValue()} className="text-fg-subtle text-xs tabular-nums">
            {formatRelative(info.getValue())}
          </time>
        ),
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: query.data?.items ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="flex flex-col">
      <PageHeader
        title="Influencers"
        description="Virtual characters in this organization."
        actions={
          mayCreate ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus aria-hidden />
              New influencer
            </Button>
          ) : null
        }
      />

      <div className="flex flex-col gap-4 px-6 py-6">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="filter-search" className="text-fg-muted text-xs font-medium">
              Search
            </label>
            <Input
              id="filter-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name or code"
              className="w-56"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="filter-status" className="text-fg-muted text-xs font-medium">
              Status
            </label>
            <Select
              id="filter-status"
              value={status}
              onChange={(event) => setStatus(event.target.value as InfluencerStatus | "all")}
              className="w-40"
            >
              <option value="all">All statuses</option>
              {INFLUENCER_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0).toUpperCase() + value.slice(1)}
                </option>
              ))}
            </Select>
          </div>
          {query.data ? (
            <p className="text-fg-subtle pb-2.5 text-xs">
              {query.data.total} {query.data.total === 1 ? "influencer" : "influencers"}
            </p>
          ) : null}
        </div>

        {query.error ? (
          <ErrorNotice message={describeError(query.error)} requestId={requestIdOf(query.error)} />
        ) : query.isLoading ? (
          <div className="flex flex-col gap-2">
            {[0, 1, 2, 3].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        ) : table.getRowModel().rows.length === 0 ? (
          <EmptyState
            icon={<Users className="size-6" />}
            title="No influencers match these filters"
            description={
              mayCreate
                ? "Create a character to start building its Character Bible."
                : "Ask a creative lead to create one."
            }
            action={
              mayCreate ? (
                <Button variant="secondary" onClick={() => setCreateOpen(true)}>
                  <Plus aria-hidden />
                  New influencer
                </Button>
              ) : null
            }
          />
        ) : (
          <TableWrapper>
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      const sorted = header.column.getIsSorted();
                      return (
                        <TableHead key={header.id}>
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className="hover:text-fg inline-flex items-center gap-1 uppercase"
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" ? (
                              <ArrowUp className="size-3" aria-hidden />
                            ) : sorted === "desc" ? (
                              <ArrowDown className="size-3" aria-hidden />
                            ) : null}
                          </button>
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableWrapper>
        )}
      </div>

      <CreateInfluencerDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

function isInfluencerStatus(value: string | null): value is InfluencerStatus {
  return value !== null && (INFLUENCER_STATUSES as readonly string[]).includes(value);
}
