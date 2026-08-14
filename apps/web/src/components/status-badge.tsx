import { Badge } from "@influenceros/ui";
import type { ActorType, InfluencerStatus } from "@influenceros/types";

import { humaniseSnakeCase } from "@/lib/format";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const INFLUENCER_TONES: Record<InfluencerStatus, Tone> = {
  draft: "info",
  active: "success",
  paused: "warning",
  archived: "neutral",
};

/**
 * Influencer status pill.
 *
 * The status word is always rendered, so the colour is redundant reinforcement
 * rather than the only carrier of meaning.
 */
export function InfluencerStatusBadge({ status }: { status: InfluencerStatus }) {
  return <Badge tone={INFLUENCER_TONES[status]}>{humaniseSnakeCase(status)}</Badge>;
}

const ACTOR_TONES: Record<ActorType, Tone> = {
  user: "neutral",
  // An automated actor is highlighted on purpose: "who did this, a person or a
  // machine" is the first question asked of an audit entry.
  agent: "warning",
  system: "info",
};

export function ActorTypeBadge({ actorType }: { actorType: ActorType }) {
  return <Badge tone={ACTOR_TONES[actorType]}>{humaniseSnakeCase(actorType)}</Badge>;
}

export function RoleBadge({ role }: { role: string }) {
  return <Badge tone={role === "agent" ? "warning" : "neutral"}>{humaniseSnakeCase(role)}</Badge>;
}
