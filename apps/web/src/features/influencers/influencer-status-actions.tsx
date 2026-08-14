"use client";

import type { InfluencerDetail, InfluencerStatus } from "@influenceros/types";
import { INFLUENCER_TRANSITIONS } from "@influenceros/types";
import { Button } from "@influenceros/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { useSession } from "@/hooks/use-session";
import { influencersApi, queryKeys } from "@/lib/api";
import { humaniseSnakeCase } from "@/lib/format";
import { PERMISSIONS, can } from "@/lib/permissions";

/**
 * Lifecycle actions.
 *
 * Which buttons appear comes from a copy of the backend's transition table, so the
 * UI never offers a move the server would refuse. That copy is an affordance only:
 * the state machine and the activation preconditions are enforced server-side, so a
 * stale table here can at worst show a button that returns 409.
 */
export function InfluencerStatusActions({ influencer }: { influencer: InfluencerDetail }) {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<InfluencerStatus | null>(null);

  const mayUpdate = can(me, PERMISSIONS.influencerUpdate);
  const mayArchive = can(me, PERMISSIONS.influencerArchive);

  const changeStatus = useMutation({
    mutationFn: (next: InfluencerStatus) => influencersApi.changeStatus(influencer.id, next),
    onSuccess: async (updated) => {
      queryClient.setQueryData(queryKeys.influencer(influencer.id), updated);
      await queryClient.invalidateQueries({ queryKey: ["influencers"] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.influencerHistory(influencer.id) });
      setTarget(null);
    },
  });

  const available = INFLUENCER_TRANSITIONS[influencer.status].filter((next) =>
    next === "archived" ? mayArchive : mayUpdate,
  );

  if (available.length === 0) return null;

  const blockers = influencer.activation_blockers;

  return (
    <>
      <div className="flex items-center gap-2">
        {available.map((next) => {
          const isArchive = next === "archived";
          // Activation is disabled rather than hidden, so the blocker banner above
          // explains why instead of the button silently vanishing.
          const blockedByPreconditions = next === "active" && blockers.length > 0;
          return (
            <Button
              key={next}
              size="sm"
              variant={isArchive ? "danger" : next === "active" ? "primary" : "secondary"}
              onClick={() => setTarget(next)}
              disabled={blockedByPreconditions}
              title={blockedByPreconditions ? `Blocked: ${blockers.join("; ")}` : undefined}
            >
              {actionLabel(next)}
            </Button>
          );
        })}
      </div>

      <ConfirmDialog
        open={target !== null}
        onOpenChange={(open) => {
          if (!open) {
            setTarget(null);
            changeStatus.reset();
          }
        }}
        title={target ? `${actionLabel(target)} ${influencer.public_name}?` : ""}
        description={target ? describeTransition(target, influencer) : ""}
        confirmLabel={target ? actionLabel(target) : ""}
        variant={target === "archived" ? "danger" : "primary"}
        // Archiving is terminal, so it takes a typed confirmation rather than a
        // single click.
        confirmationPhrase={target === "archived" ? influencer.code : undefined}
        pending={changeStatus.isPending}
        error={changeStatus.error}
        onConfirm={() => {
          if (target) changeStatus.mutate(target);
        }}
      />
    </>
  );
}

function actionLabel(status: InfluencerStatus): string {
  switch (status) {
    case "active":
      return "Activate";
    case "paused":
      return "Pause";
    case "archived":
      return "Archive";
    case "draft":
      return "Return to draft";
    default:
      return humaniseSnakeCase(status);
  }
}

function describeTransition(target: InfluencerStatus, influencer: InfluencerDetail): string {
  switch (target) {
    case "active":
      return "The character becomes available for content production.";
    case "paused":
      return "Production stops. The character can be reactivated later.";
    case "archived":
      return (
        `Archiving is permanent: '${influencer.code}' cannot be reactivated, edited, or given ` +
        "new Character Bible versions. Its history stays readable, and a replacement character " +
        "would need a new code."
      );
    default:
      return "";
  }
}
