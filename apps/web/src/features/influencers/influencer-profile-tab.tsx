"use client";

import type { InfluencerDetail } from "@influenceros/types";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ErrorNotice,
  Field,
  Input,
} from "@influenceros/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useSession } from "@/hooks/use-session";
import { influencersApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { PERMISSIONS, can } from "@/lib/permissions";

const schema = z.object({
  public_name: z.string().min(1, "Required").max(200),
  niche: z.string().max(200).optional(),
  primary_language: z.string().regex(/^[a-z]{2}(-[A-Z]{2})?$/, "Use a tag like 'en' or 'pt-BR'"),
  primary_market: z.string().regex(/^[A-Z]{2}$/, "Two uppercase letters"),
  adult_representation_confirmed: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export function InfluencerProfileTab({ influencer }: { influencer: InfluencerDetail }) {
  const { me } = useSession();
  const queryClient = useQueryClient();
  const isArchived = influencer.status === "archived";
  const mayEdit = can(me, PERMISSIONS.influencerUpdate) && !isArchived;

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: {
      public_name: influencer.public_name,
      niche: influencer.niche ?? "",
      primary_language: influencer.primary_language,
      primary_market: influencer.primary_market,
      adult_representation_confirmed: influencer.adult_representation_confirmed,
    },
  });

  const update = useMutation({
    mutationFn: (values: FormValues) =>
      influencersApi.update(influencer.id, {
        public_name: values.public_name,
        niche: values.niche?.trim() ? values.niche.trim() : null,
        primary_language: values.primary_language,
        primary_market: values.primary_market,
        adult_representation_confirmed: values.adult_representation_confirmed,
      }),
    onSuccess: async (updated) => {
      queryClient.setQueryData(queryKeys.influencer(influencer.id), updated);
      await queryClient.invalidateQueries({ queryKey: ["influencers"] });
      await queryClient.invalidateQueries({ queryKey: queryKeys.influencerHistory(influencer.id) });
      reset(undefined, { keepValues: true });
    },
  });

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            {isArchived
              ? "Archived influencers are read-only."
              : mayEdit
                ? "The code cannot be changed: it is the stable identifier used in storage keys and audit rows."
                : "Your role cannot edit this influencer."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={handleSubmit((values) => update.mutate(values))}
            noValidate
          >
            <fieldset disabled={!mayEdit} className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Public name"
                htmlFor="detail_public_name"
                error={errors.public_name?.message}
                required
              >
                <Input {...register("public_name")} />
              </Field>

              <Field label="Code" htmlFor="detail_code" hint="Immutable">
                <Input value={influencer.code} readOnly disabled className="font-mono" />
              </Field>

              <Field
                label="Primary language"
                htmlFor="detail_primary_language"
                error={errors.primary_language?.message}
                required
              >
                <Input className="font-mono" {...register("primary_language")} />
              </Field>

              <Field
                label="Primary market"
                htmlFor="detail_primary_market"
                error={errors.primary_market?.message}
                required
              >
                <Input className="font-mono" {...register("primary_market")} />
              </Field>

              <Field label="Niche" htmlFor="detail_niche" error={errors.niche?.message}>
                <Input {...register("niche")} />
              </Field>
            </fieldset>

            <label className="border-border bg-surface-2 flex items-start gap-2.5 rounded-md border px-3 py-2.5">
              <input
                type="checkbox"
                disabled={!mayEdit}
                className="mt-0.5 size-4 accent-[var(--color-accent)]"
                {...register("adult_representation_confirmed")}
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-fg text-sm">This character depicts an adult</span>
                <span className="text-fg-subtle text-xs">
                  {influencer.status === "active"
                    ? "Cannot be withdrawn while active — pause the influencer first."
                    : "Required before activation."}
                </span>
              </span>
            </label>

            {update.error ? (
              <ErrorNotice
                title="Could not save"
                message={describeError(update.error)}
                requestId={requestIdOf(update.error)}
              />
            ) : null}

            {mayEdit ? (
              <div className="flex items-center gap-2">
                <Button type="submit" loading={update.isPending} disabled={!isDirty}>
                  Save changes
                </Button>
                {update.isSuccess && !isDirty ? (
                  <span className="text-success-fg text-xs">Saved</span>
                ) : null}
              </div>
            ) : null}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Record</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="flex flex-col gap-3 text-sm">
            <MetaRow label="Status" value={influencer.status} />
            <MetaRow
              label="Character Bible"
              value={
                influencer.current_version_number
                  ? `version ${influencer.current_version_number}`
                  : "none yet"
              }
            />
            <MetaRow label="Created" value={formatDateTime(influencer.created_at)} />
            <MetaRow label="Updated" value={formatDateTime(influencer.updated_at)} />
            {influencer.archived_at ? (
              <MetaRow label="Archived" value={formatDateTime(influencer.archived_at)} />
            ) : null}
            <MetaRow label="ID" value={influencer.id} mono />
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function MetaRow({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-fg-subtle text-xs uppercase tracking-wide">{label}</dt>
      <dd className={mono ? "text-fg-muted break-all font-mono text-xs" : "text-fg"}>{value}</dd>
    </div>
  );
}
