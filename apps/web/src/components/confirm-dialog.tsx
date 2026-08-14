"use client";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  ErrorNotice,
  Field,
  Input,
} from "@influenceros/ui";
import { useState, type ReactNode } from "react";

import { describeError, requestIdOf } from "@/lib/api-client";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  /** `danger` styles the confirm button as destructive. */
  variant?: "primary" | "danger";
  /**
   * When set, the confirm button stays disabled until the user types this exactly.
   * Reserved for irreversible actions, where an accidental click is the risk.
   */
  confirmationPhrase?: string;
  pending?: boolean;
  error?: unknown;
  onConfirm: () => void;
}

/**
 * Confirmation for a consequential action.
 *
 * Every destructive action in the app routes through this, so the copy and the
 * typed-phrase requirement cannot vary per call site.
 */
export function ConfirmDialog({ open, onOpenChange, ...body }: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {/* Radix mounts content only while open, so the body's state is created
            fresh each time the dialog appears. That is what resets the typed
            confirmation phrase — no effect, and no chance of a previous entry
            pre-arming the confirm button. */}
        <ConfirmDialogBody {...body} onCancel={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

type ConfirmDialogBodyProps = Omit<ConfirmDialogProps, "open" | "onOpenChange"> & {
  onCancel: () => void;
};

function ConfirmDialogBody({
  title,
  description,
  confirmLabel,
  variant = "primary",
  confirmationPhrase,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: ConfirmDialogBodyProps) {
  const [typed, setTyped] = useState("");
  const phraseSatisfied = !confirmationPhrase || typed.trim() === confirmationPhrase;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription asChild>
          <div>{description}</div>
        </DialogDescription>
      </DialogHeader>

      {confirmationPhrase ? (
        <Field
          label={`Type "${confirmationPhrase}" to confirm`}
          htmlFor="confirm-phrase"
          hint="This action cannot be undone."
        >
          <Input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
      ) : null}

      {error ? <ErrorNotice message={describeError(error)} requestId={requestIdOf(error)} /> : null}

      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button variant={variant} onClick={onConfirm} loading={pending} disabled={!phraseSatisfied}>
          {confirmLabel}
        </Button>
      </DialogFooter>
    </>
  );
}
