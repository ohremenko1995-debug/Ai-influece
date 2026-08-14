import * as React from "react";

import { cn } from "./lib/cn";

/**
 * Unstyled-ish table primitives. Density is medium by design: this is an internal
 * tool where operators scan many rows, so rows are compact but not cramped.
 *
 * The wrapper scrolls horizontally on its own so a wide table never makes the page
 * body scroll sideways.
 */
export function TableWrapper({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("border-border w-full overflow-x-auto rounded-lg border", className)}
      {...props}
    />
  );
}

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full caption-bottom text-sm", className)} {...props} />;
}

export function TableHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-surface-2", className)} {...props} />;
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-border divide-y", className)} {...props} />;
}

export function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("hover:bg-surface-2/60 transition-colors", className)} {...props} />;
}

export function TableHead({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn(
        "text-fg-subtle px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("text-fg px-3 py-2 align-middle", className)} {...props} />;
}
