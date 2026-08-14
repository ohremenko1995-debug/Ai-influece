"use client";

import * as LabelPrimitive from "@radix-ui/react-label";
import * as React from "react";

import { cn } from "./lib/cn";

const controlClasses =
  "w-full rounded-md border border-border bg-surface-2 px-3 py-2 text-sm text-fg " +
  "placeholder:text-fg-subtle focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 " +
  "aria-[invalid=true]:border-danger-border";

export const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(function Label({ className, ...props }, ref) {
  return (
    <LabelPrimitive.Root
      ref={ref}
      className={cn("text-fg-muted text-xs font-medium", className)}
      {...props}
    />
  );
});

export const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  function Input({ className, ...props }, ref) {
    return <input ref={ref} className={cn(controlClasses, className)} {...props} />;
  },
);

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={cn(controlClasses, "min-h-20 resize-y", className)}
        {...props}
      />
    );
  },
);

export const Select = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(
  function Select({ className, ...props }, ref) {
    return <select ref={ref} className={cn(controlClasses, "pr-8", className)} {...props} />;
  },
);

export interface FieldProps {
  label: string;
  htmlFor: string;
  /** Validation message. Its presence is what marks the field invalid. */
  error?: string | undefined;
  hint?: string | undefined;
  required?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * Label + control + message, wired for screen readers.
 *
 * The error is rendered in a live region and referenced by `aria-describedby` on
 * the control, so a validation failure is announced rather than only coloured.
 */
export function Field({
  label,
  htmlFor,
  error,
  hint,
  required = false,
  children,
  className,
}: FieldProps) {
  const describedBy = error ? `${htmlFor}-error` : hint ? `${htmlFor}-hint` : undefined;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="text-danger-fg ml-1" aria-hidden>
            *
          </span>
        ) : null}
      </Label>
      {React.isValidElement(children)
        ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            id: htmlFor,
            "aria-invalid": error ? true : undefined,
            "aria-describedby": describedBy,
          })
        : children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="text-danger-fg text-xs">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-fg-subtle text-xs">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
