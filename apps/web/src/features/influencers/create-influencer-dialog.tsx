"use client";

import { zodResolver } from "@hookform/resolvers/zod";
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
  Select,
} from "@influenceros/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { influencersApi, policiesApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";

/**
 * Mirrors the backend's `InfluencerCreate` validators.
 *
 * Duplicated on purpose: client validation is for immediate feedback, and the
 * server re-validates everything. Where the two could drift, the messages point at
 * the same rule so a mismatch is obvious in review.
 */
const schema = z.object({
  code: z
    .string()
    .min(3, "At least 3 characters")
    .max(64, "At most 64 characters")
    .regex(
      /^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$/,
      "Lowercase letters, digits, '-' and '_' only; must start and end with a letter or digit",
    ),
  public_name: z.string().min(1, "Required").max(200, "At most 200 characters"),
  primary_language: z.string().regex(/^[a-z]{2}(-[A-Z]{2})?$/, "Use a tag like 'en' or 'pt-BR'"),
  primary_market: z.string().regex(/^[A-Z]{2}$/, "Two uppercase letters, e.g. 'DE'"),
  niche: z.string().max(200, "At most 200 characters").optional(),
  disclosure_policy_id: z.string().optional(),
  adult_representation_confirmed: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

export function CreateInfluencerDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const policies = useQuery({
    queryKey: queryKeys.policies,
    queryFn: () => policiesApi.list(),
    enabled: open,
  });

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: "",
      public_name: "",
      primary_language: "en",
      primary_market: "DE",
      niche: "",
      disclosure_policy_id: "",
      adult_representation_confirmed: false,
    },
  });

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  // Preselect the organization's default policy — activation requires one, so
  // leaving it blank creates a character that immediately needs editing.
  useEffect(() => {
    const defaultPolicy = policies.data?.find((policy) => policy.is_default);
    if (defaultPolicy) setValue("disclosure_policy_id", defaultPolicy.id);
  }, [policies.data, setValue]);

  const create = useMutation({
    mutationFn: (values: FormValues) =>
      influencersApi.create({
        code: values.code,
        public_name: values.public_name,
        primary_language: values.primary_language,
        primary_market: values.primary_market,
        niche: values.niche?.trim() ? values.niche.trim() : null,
        disclosure_policy_id: values.disclosure_policy_id || null,
        adult_representation_confirmed: values.adult_representation_confirmed,
      }),
    onSuccess: async (influencer) => {
      await queryClient.invalidateQueries({ queryKey: ["influencers"] });
      onOpenChange(false);
      router.push(`/influencers/${influencer.id}`);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New influencer</DialogTitle>
          <DialogDescription>
            Created in <strong>draft</strong>. Activation additionally requires a Character Bible
            version, so the next step is writing one.
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={handleSubmit((values) => create.mutate(values))}
          noValidate
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Public name"
              htmlFor="public_name"
              error={errors.public_name?.message}
              required
            >
              <Input placeholder="Nora" {...register("public_name")} />
            </Field>

            <Field
              label="Code"
              htmlFor="code"
              error={errors.code?.message}
              hint="Stable internal identifier. Cannot be changed later."
              required
            >
              <Input placeholder="nora" className="font-mono" {...register("code")} />
            </Field>

            <Field
              label="Primary language"
              htmlFor="primary_language"
              error={errors.primary_language?.message}
              required
            >
              <Input placeholder="en" className="font-mono" {...register("primary_language")} />
            </Field>

            <Field
              label="Primary market"
              htmlFor="primary_market"
              error={errors.primary_market?.message}
              hint="ISO 3166-1 alpha-2"
              required
            >
              <Input placeholder="DE" className="font-mono" {...register("primary_market")} />
            </Field>

            <Field label="Niche" htmlFor="niche" error={errors.niche?.message}>
              <Input placeholder="fitness" {...register("niche")} />
            </Field>

            <Field
              label="Disclosure policy"
              htmlFor="disclosure_policy_id"
              error={errors.disclosure_policy_id?.message}
              hint="Required before the character can be activated."
            >
              <Select {...register("disclosure_policy_id")}>
                <option value="">None selected</option>
                {policies.data?.map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {policy.name}
                    {policy.is_default ? " (default)" : ""}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <label className="border-border bg-surface-2 flex items-start gap-2.5 rounded-md border px-3 py-2.5">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-[var(--color-accent)]"
              {...register("adult_representation_confirmed")}
            />
            <span className="flex flex-col gap-0.5">
              <span className="text-fg text-sm">This character depicts an adult</span>
              <span className="text-fg-subtle text-xs">
                An explicit compliance record. Required before activation, and it cannot be
                withdrawn while the character is active.
              </span>
            </span>
          </label>

          {create.error ? (
            <ErrorNotice
              title="Could not create the influencer"
              message={describeError(create.error)}
              requestId={requestIdOf(create.error)}
            />
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" loading={create.isPending}>
              Create influencer
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
