"use client";

import type { InfluencerDetail, InfluencerVersionRead } from "@influenceros/types";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorNotice,
  Field,
  Input,
  Skeleton,
  Textarea,
  cn,
} from "@influenceros/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { useSession } from "@/hooks/use-session";
import { influencersApi, queryKeys } from "@/lib/api";
import { describeError, requestIdOf } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { PERMISSIONS, can } from "@/lib/permissions";

/**
 * Character Bible.
 *
 * Versions are immutable, so there is no edit form — only "append a new version".
 * The version list is the primary navigation, and selecting an old version shows
 * exactly what was in force then.
 */
export function CharacterBibleTab({ influencer }: { influencer: InfluencerDetail }) {
  const { me } = useSession();
  const isArchived = influencer.status === "archived";
  const mayCreate = can(me, PERMISSIONS.influencerVersionCreate) && !isArchived;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);

  const versions = useQuery({
    queryKey: queryKeys.influencerVersions(influencer.id),
    queryFn: () => influencersApi.listVersions(influencer.id),
  });

  const items = versions.data?.items ?? [];
  const selected = items.find((item) => item.id === selectedId) ?? items[0];

  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <Card>
        <CardHeader>
          <CardTitle>Versions</CardTitle>
          <CardDescription>
            Append-only. Editing identity creates a new version; earlier ones stay readable.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {mayCreate ? (
            <Button size="sm" onClick={() => setComposerOpen(true)}>
              <Plus aria-hidden />
              New version
            </Button>
          ) : isArchived ? (
            <p className="text-fg-subtle text-xs">Archived influencers are read-only.</p>
          ) : null}

          {versions.isLoading ? (
            <div className="flex flex-col gap-2 pt-1">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : items.length === 0 ? (
            <p className="text-fg-subtle pt-1 text-xs">No versions yet.</p>
          ) : (
            <ul className="flex flex-col gap-1 pt-1">
              {items.map((version) => {
                const isSelected = selected?.id === version.id;
                return (
                  <li key={version.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(version.id)}
                      className={cn(
                        "flex w-full flex-col gap-0.5 rounded-md px-3 py-2 text-left transition-colors",
                        isSelected ? "bg-surface-3" : "hover:bg-surface-2",
                      )}
                      aria-current={isSelected ? "true" : undefined}
                    >
                      <span className="flex items-center gap-2">
                        <span className="text-fg text-sm font-medium">
                          Version {version.version_number}
                        </span>
                        {version.is_current ? <Badge tone="success">Current</Badge> : null}
                      </span>
                      <span className="text-fg-subtle truncate text-xs">
                        {version.change_summary}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="min-w-0">
        {versions.error ? (
          <ErrorNotice
            message={describeError(versions.error)}
            requestId={requestIdOf(versions.error)}
          />
        ) : selected ? (
          <VersionDetail version={selected} />
        ) : versions.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : (
          <EmptyState
            icon={<BookOpen className="size-6" />}
            title="No Character Bible yet"
            description="A character cannot be activated without one. It records the biography, tone of voice, prohibited topics and the visual and speech constraints every generation must respect."
            action={
              mayCreate ? (
                <Button variant="secondary" onClick={() => setComposerOpen(true)}>
                  <Plus aria-hidden />
                  Write version 1
                </Button>
              ) : null
            }
          />
        )}
      </div>

      <BibleComposer
        influencerId={influencer.id}
        nextVersion={(items[0]?.version_number ?? 0) + 1}
        open={composerOpen}
        onOpenChange={setComposerOpen}
        onCreated={(version) => setSelectedId(version.id)}
      />
    </div>
  );
}

function VersionDetail({ version }: { version: InfluencerVersionRead }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>Version {version.version_number}</CardTitle>
          {version.is_current ? (
            <Badge tone="success">Current</Badge>
          ) : (
            <Badge tone="neutral">Superseded</Badge>
          )}
        </div>
        <CardDescription>
          {version.change_summary} · created {formatDateTime(version.created_at)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <Section title="Biography">
          <Prose text={version.biography} />
        </Section>
        <Section title="Tone of voice">
          <Prose text={version.tone_of_voice} />
        </Section>
        <Section title="Personality traits">
          <Chips values={version.personality_traits} tone="info" />
        </Section>
        <Section title="Prohibited topics" hint="This character must never speak about these.">
          <Chips values={version.prohibited_topics} tone="danger" />
        </Section>
        <Section title="Visual constraints">
          <JsonBlock value={version.visual_constraints} />
        </Section>
        <Section title="Speech constraints">
          <JsonBlock value={version.speech_constraints} />
        </Section>
      </CardContent>
    </Card>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-1.5">
      <h4 className="text-fg-subtle text-xs font-semibold uppercase tracking-wide">{title}</h4>
      {hint ? <p className="text-fg-subtle text-xs">{hint}</p> : null}
      {children}
    </section>
  );
}

function Prose({ text }: { text: string | null }) {
  if (!text) return <p className="text-fg-subtle text-sm">Not set.</p>;
  return <p className="text-fg-muted whitespace-pre-wrap text-sm">{text}</p>;
}

function Chips({ values, tone }: { values: string[]; tone: "info" | "danger" }) {
  if (values.length === 0) return <p className="text-fg-subtle text-sm">None.</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {values.map((value) => (
        <li key={value}>
          <Badge tone={tone}>{value}</Badge>
        </li>
      ))}
    </ul>
  );
}

function JsonBlock({ value }: { value: Record<string, unknown> }) {
  if (Object.keys(value).length === 0) return <p className="text-fg-subtle text-sm">None.</p>;
  return (
    <pre className="border-border bg-surface-2 text-fg-muted overflow-x-auto rounded-md border px-3 py-2 font-mono text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// --- Composer ----------------------------------------------------------------

const bibleSchema = z.object({
  change_summary: z.string().min(3, "At least 3 characters").max(500),
  biography: z.string().max(10_000).optional(),
  tone_of_voice: z.string().max(4_000).optional(),
  personality_traits: z.string().optional(),
  prohibited_topics: z.string().optional(),
  visual_constraints: z.string().optional(),
  speech_constraints: z.string().optional(),
});

type BibleFormValues = z.infer<typeof bibleSchema>;

interface BibleComposerProps {
  influencerId: string;
  nextVersion: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (version: InfluencerVersionRead) => void;
}

function BibleComposer({ open, onOpenChange, ...rest }: BibleComposerProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        {/* The form lives in a child so that Radix unmounting the content when the
            dialog closes is what clears it. Resetting from an effect instead would
            trigger a cascading render, which React Compiler rightly flags. */}
        <BibleComposerForm {...rest} onCancel={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function BibleComposerForm({
  influencerId,
  nextVersion,
  onCreated,
  onCancel,
}: Omit<BibleComposerProps, "open" | "onOpenChange"> & { onCancel: () => void }) {
  const queryClient = useQueryClient();
  const [jsonError, setJsonError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<BibleFormValues>({
    resolver: zodResolver(bibleSchema),
    defaultValues: {
      change_summary: "",
      biography: "",
      tone_of_voice: "",
      personality_traits: "",
      prohibited_topics: "",
      visual_constraints: "",
      speech_constraints: "",
    },
  });

  const create = useMutation({
    mutationFn: (values: BibleFormValues) =>
      influencersApi.createVersion(influencerId, {
        change_summary: values.change_summary,
        biography: values.biography?.trim() ? values.biography : null,
        tone_of_voice: values.tone_of_voice?.trim() ? values.tone_of_voice : null,
        personality_traits: splitList(values.personality_traits),
        prohibited_topics: splitList(values.prohibited_topics),
        visual_constraints: parseJsonObject(values.visual_constraints),
        speech_constraints: parseJsonObject(values.speech_constraints),
      }),
    onSuccess: async (version) => {
      await queryClient.invalidateQueries({
        queryKey: queryKeys.influencerVersions(influencerId),
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.influencer(influencerId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.influencerHistory(influencerId) });
      onCreated(version);
      onCancel();
    },
  });

  function onSubmit(values: BibleFormValues) {
    // JSON is validated here rather than in the zod schema so the message can name
    // which of the two fields is malformed.
    for (const field of ["visual_constraints", "speech_constraints"] as const) {
      const raw = values[field];
      if (raw?.trim() && !isJsonObject(raw)) {
        setJsonError(
          `${field.replace("_", " ")} must be a JSON object, e.g. {"eye_color": "green"}`,
        );
        return;
      }
    }
    setJsonError(null);
    create.mutate(values);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Character Bible version {nextVersion}</DialogTitle>
        <DialogDescription>
          A version is a complete snapshot, not a patch — fill in the full identity as it should
          stand from now on. Versions are immutable once created.
        </DialogDescription>
      </DialogHeader>

      <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)} noValidate>
        <Field
          label="Change summary"
          htmlFor="change_summary"
          error={errors.change_summary?.message}
          hint="Why this revision exists. Shown in the version history."
          required
        >
          <Input
            placeholder="Softened tone; added two prohibited topics"
            {...register("change_summary")}
          />
        </Field>

        <Field label="Biography" htmlFor="biography" error={errors.biography?.message}>
          <Textarea rows={4} {...register("biography")} />
        </Field>

        <Field label="Tone of voice" htmlFor="tone_of_voice" error={errors.tone_of_voice?.message}>
          <Textarea rows={2} {...register("tone_of_voice")} />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Personality traits"
            htmlFor="personality_traits"
            hint="One per line, or comma-separated"
          >
            <Textarea
              rows={3}
              placeholder={"disciplined\nencouraging"}
              {...register("personality_traits")}
            />
          </Field>
          <Field
            label="Prohibited topics"
            htmlFor="prohibited_topics"
            hint="One per line. The character must never speak about these."
          >
            <Textarea
              rows={3}
              placeholder={"medical advice\npolitics"}
              {...register("prohibited_topics")}
            />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Visual constraints"
            htmlFor="visual_constraints"
            hint='JSON object, e.g. {"eye_color": "green"}'
          >
            <Textarea rows={3} className="font-mono text-xs" {...register("visual_constraints")} />
          </Field>
          <Field
            label="Speech constraints"
            htmlFor="speech_constraints"
            hint='JSON object, e.g. {"max_wpm": 165}'
          >
            <Textarea rows={3} className="font-mono text-xs" {...register("speech_constraints")} />
          </Field>
        </div>

        {jsonError ? <ErrorNotice title="Invalid JSON" message={jsonError} /> : null}
        {create.error ? (
          <ErrorNotice
            title="Could not create the version"
            message={describeError(create.error)}
            requestId={requestIdOf(create.error)}
          />
        ) : null}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={onCancel} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" loading={create.isPending}>
            Create version {nextVersion}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}

/** Split a textarea into a de-duplicated list, accepting newlines or commas. */
export function splitList(raw: string | undefined): string[] {
  if (!raw) return [];
  const parts = raw
    .split(/[\n,]/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  // The backend rejects case-insensitive duplicates, so de-duplicate here rather
  // than letting the user hit a 422 for something the UI could resolve.
  const seen = new Set<string>();
  const result: string[] = [];
  for (const part of parts) {
    const key = part.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(part);
  }
  return result;
}

export function isJsonObject(raw: string): boolean {
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
  } catch {
    return false;
  }
}

export function parseJsonObject(raw: string | undefined): Record<string, unknown> {
  if (!raw?.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  } catch {
    // Validated before submit; an unparseable value here means the guard was
    // bypassed, and an empty object is safer than throwing during a mutation.
  }
  return {};
}
