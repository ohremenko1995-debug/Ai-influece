"use client";

import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "./lib/cn";

/**
 * Status pill.
 *
 * Every tone pairs a background with a border and readable text rather than
 * relying on hue alone — status must survive a monochrome screen and the common
 * forms of colour blindness. The label text always states the status too, so
 * colour is reinforcement, never the only signal.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface-2 text-fg-muted",
        info: "border-info-border bg-info-bg text-info-fg",
        success: "border-success-border bg-success-bg text-success-fg",
        warning: "border-warning-border bg-warning-bg text-warning-fg",
        danger: "border-danger-border bg-danger-bg text-danger-fg",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { badgeVariants };
