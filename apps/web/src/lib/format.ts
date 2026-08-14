/** Display formatting helpers. */

const dateTimeFormatter = new Intl.DateTimeFormat("en-GB", {
  year: "numeric",
  month: "short",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

/**
 * Absolute timestamp, always in UTC.
 *
 * An audit trail read by people in different timezones is only comparable if every
 * timestamp uses one, and the suffix says which.
 */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return `${dateTimeFormatter.format(date)} UTC`;
}

const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const DIVISIONS: readonly [Intl.RelativeTimeFormatUnit, number][] = [
  ["second", 60],
  ["minute", 60],
  ["hour", 24],
  ["day", 7],
  ["week", 4.35],
  ["month", 12],
  ["year", Number.POSITIVE_INFINITY],
];

/** "3 minutes ago". Pair with an absolute value in a tooltip, never on its own. */
export function formatRelative(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";

  let duration = (date.getTime() - now.getTime()) / 1000;
  for (const [unit, amount] of DIVISIONS) {
    if (Math.abs(duration) < amount) return relativeFormatter.format(Math.round(duration), unit);
    duration /= amount;
  }
  return relativeFormatter.format(Math.round(duration), "year");
}

/** `influencer_version.promoted` -> `Influencer version promoted`. */
export function humaniseAction(action: string): string {
  const words = action.replace(/[._]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** `creative_lead` -> `Creative lead`. */
export function humaniseSnakeCase(value: string): string {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Compact JSON for an audit diff cell. Long values are truncated, not wrapped. */
export function formatFieldValue(value: unknown, maxLength = 60): string {
  if (value === null || value === undefined) return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength - 1)}…`;
}
