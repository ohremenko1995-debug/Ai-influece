"use client";

import type { InfluencerDetail } from "@influenceros/types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ErrorNotice,
  Select,
} from "@influenceros/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { useSession } from "@/hooks/use-session";
import { influencersApi, policiesApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { PERMISSIONS, can } from "@/lib/permissions";

/**
 * Disclosure policy for this character.
 *
 * The policy is what the platform can later prove it required: that the character
 * is declared AI-generated, and how advertising is disclosed.
 */
export function InfluencerPoliciesTab({ influencer }: { influencer: InfluencerDetail }) {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const isArchived = influencer.status === "archived";
  const mayAssign = can(me, PERMISSIONS.influencerUpdate) && !isArchived;
  const [selected, setSelected] = useState(influencer.disclosure_policy_id ?? "");

  const policies = useQuery({
    queryKey: queryKeys.policies,
    queryFn: () => policiesApi.list(),
  });

  const assign = useMutation({
    mutationFn: (policyId: string) =>
      influencersApi.update(influencer.id, { disclosure_policy_id: policyId || null }),
    onSuccess: async (updated) => {
      queryClient.setQueryData(queryKeys.influencer(influencer.id), updated);
      await queryClient.invalidateQueries({ queryKey: queryKeys.influencerHistory(influencer.id) });
    },
  });

  const policy = influencer.disclosure_policy;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {policy ? (
              <ShieldCheck className="text-success-fg size-4" aria-hidden />
            ) : (
              <ShieldAlert className="text-warning-fg size-4" aria-hidden />
            )}
            Disclosure policy
          </CardTitle>
          <CardDescription>
            {policy
              ? "Applied to every piece of content produced for this character."
              : "None assigned. The character cannot be activated without one."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {policy ? (
            <dl className="flex flex-col gap-4 text-sm">
              <div className="flex flex-col gap-1">
                <dt className="text-fg-subtle text-xs uppercase tracking-wide">Policy</dt>
                <dd className="text-fg flex items-center gap-2">
                  {policy.name}
                  {policy.is_default ? <Badge tone="info">Organization default</Badge> : null}
                </dd>
              </div>

              <div className="flex flex-col gap-1">
                <dt className="text-fg-subtle flex items-center gap-2 text-xs uppercase tracking-wide">
                  AI disclosure
                  <Badge tone={policy.ai_disclosure_required ? "success" : "warning"}>
                    {policy.ai_disclosure_required ? "Required" : "Not required"}
                  </Badge>
                </dt>
                <dd className="border-border bg-surface-2 text-fg-muted rounded-md border px-3 py-2">
                  {policy.ai_disclosure_text}
                </dd>
              </div>

              <div className="flex flex-col gap-1">
                <dt className="text-fg-subtle flex items-center gap-2 text-xs uppercase tracking-wide">
                  Advertising disclosure
                  <Badge tone={policy.advertising_disclosure_required ? "success" : "warning"}>
                    {policy.advertising_disclosure_required ? "Required" : "Not required"}
                  </Badge>
                </dt>
                <dd className="border-border bg-surface-2 text-fg-muted rounded-md border px-3 py-2">
                  {policy.advertising_disclosure_text}
                </dd>
              </div>

              <div className="flex flex-col gap-1">
                <dt className="text-fg-subtle text-xs uppercase tracking-wide">
                  High-risk content
                </dt>
                <dd className="text-fg-muted">
                  {policy.requires_high_risk_approval
                    ? "Requires a compliance decision, not an ordinary review."
                    : "Follows the standard approval route."}
                </dd>
              </div>
            </dl>
          ) : null}

          {mayAssign ? (
            <div className="border-border flex flex-col gap-2 border-t pt-4">
              <label htmlFor="assign-policy" className="text-fg-muted text-xs font-medium">
                Assign a policy
              </label>
              <div className="flex items-center gap-2">
                <Select
                  id="assign-policy"
                  value={selected}
                  onChange={(event) => setSelected(event.target.value)}
                  className="max-w-xs"
                >
                  <option value="">None</option>
                  {policies.data?.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.name}
                      {option.is_default ? " (default)" : ""}
                    </option>
                  ))}
                </Select>
                <Button
                  size="sm"
                  onClick={() => assign.mutate(selected)}
                  loading={assign.isPending}
                  disabled={selected === (influencer.disclosure_policy_id ?? "")}
                >
                  Apply
                </Button>
              </div>
              {assign.error ? (
                <ErrorNotice
                  message={describeError(assign.error)}
                  requestId={requestIdOf(assign.error)}
                />
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Compliance record</CardTitle>
          <CardDescription>
            These are the checks the backend enforces before this character may go live.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="flex flex-col gap-3 text-sm">
            <CheckRow
              satisfied={influencer.adult_representation_confirmed}
              label="Adult representation confirmed"
              detail="An explicit record that the character depicts an adult. Never defaulted."
            />
            <CheckRow
              satisfied={influencer.disclosure_policy_id !== null}
              label="Disclosure policy assigned"
              detail="States how the character's AI nature is declared."
            />
            <CheckRow
              satisfied={influencer.current_version_number !== null}
              label="Character Bible exists"
              detail="Identity constraints every generation must respect."
            />
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function CheckRow({
  satisfied,
  label,
  detail,
}: {
  satisfied: boolean;
  label: string;
  detail: string;
}) {
  return (
    <li className="flex items-start gap-2.5">
      <span className="pt-0.5" aria-hidden>
        {satisfied ? (
          <ShieldCheck className="text-success-fg size-4" />
        ) : (
          <ShieldAlert className="text-warning-fg size-4" />
        )}
      </span>
      <span className="flex flex-col gap-0.5">
        <span className={satisfied ? "text-fg" : "text-warning-fg"}>
          {label}
          <span className="sr-only">{satisfied ? " — satisfied" : " — not satisfied"}</span>
        </span>
        <span className="text-fg-subtle text-xs">{detail}</span>
      </span>
    </li>
  );
}
