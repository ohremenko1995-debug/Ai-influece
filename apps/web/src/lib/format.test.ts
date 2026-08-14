import { describe, expect, it } from "vitest";

import {
  formatDateTime,
  formatFieldValue,
  formatRelative,
  humaniseAction,
  humaniseSnakeCase,
} from "./format";

describe("formatDateTime", () => {
  it("renders in UTC and says so, because the audit trail is read across timezones", () => {
    expect(formatDateTime("2026-08-14T09:31:24Z")).toBe("14 Aug 2026, 09:31 UTC");
  });

  it("returns a dash for an unparseable value instead of 'Invalid Date'", () => {
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-08-14T12:00:00Z");

  it.each([
    ["2026-08-14T11:59:30Z", "30 seconds ago"],
    ["2026-08-14T11:55:00Z", "5 minutes ago"],
    ["2026-08-14T09:00:00Z", "3 hours ago"],
    ["2026-08-12T12:00:00Z", "2 days ago"],
  ])("formats %s as %s", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });

  it("returns a dash for an unparseable value", () => {
    expect(formatRelative("nope", now)).toBe("—");
  });
});

describe("humanise helpers", () => {
  it("turns a dotted action name into a sentence", () => {
    expect(humaniseAction("influencer_version.promoted")).toBe("Influencer version promoted");
    expect(humaniseAction("influencer.created")).toBe("Influencer created");
  });

  it("turns a snake_case role into a label", () => {
    expect(humaniseSnakeCase("creative_lead")).toBe("Creative lead");
  });
});

describe("formatFieldValue", () => {
  it("renders a dash for null and undefined", () => {
    expect(formatFieldValue(null)).toBe("—");
    expect(formatFieldValue(undefined)).toBe("—");
  });

  it("keeps strings as-is and JSON-encodes everything else", () => {
    expect(formatFieldValue("draft")).toBe("draft");
    expect(formatFieldValue(["a", "b"])).toBe('["a","b"]');
    expect(formatFieldValue(false)).toBe("false");
  });

  it("truncates long values so a diff cell stays one line", () => {
    const result = formatFieldValue("x".repeat(200), 20);
    expect(result).toHaveLength(20);
    expect(result.endsWith("…")).toBe(true);
  });
});
