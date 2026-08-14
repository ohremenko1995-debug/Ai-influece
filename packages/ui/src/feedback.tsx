import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "./lib/cn";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" className={cn("text-fg-subtle inline-flex items-center gap-2", className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("bg-surface-3 animate-pulse rounded", className)} {...props} />;
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
}

export function EmptyState({ title, description, action, icon }: EmptyStateProps) {
  return (
    <div className="border-border flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-12 text-center">
      <span className="text-fg-subtle" aria-hidden>
        {icon ?? <Inbox className="size-6" />}
      </span>
      <div className="flex flex-col gap-1">
        <p className="text-fg text-sm font-medium">{title}</p>
        {description ? <p className="text-fg-subtle text-xs">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export interface ErrorNoticeProps {
  title?: string;
  message: string;
  /** Correlates with the server logs. Shown so a report can reference it. */
  requestId?: string | null;
  action?: React.ReactNode;
}

/**
 * Failure notice.
 *
 * Shows the request id when the API supplied one: an internal tool's users are
 * engineers, and "it broke" is far less useful to them than a correlation id.
 */
export function ErrorNotice({
  title = "Something went wrong",
  message,
  requestId,
  action,
}: ErrorNoticeProps) {
  return (
    <div
      role="alert"
      className="border-danger-border bg-danger-bg flex flex-col gap-2 rounded-lg border px-4 py-3"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="text-danger-fg size-4" aria-hidden />
        <p className="text-danger-fg text-sm font-medium">{title}</p>
      </div>
      <p className="text-fg-muted text-sm">{message}</p>
      {requestId ? (
        <p className="text-fg-subtle font-mono text-xs">request id: {requestId}</p>
      ) : null}
      {action}
    </div>
  );
}
