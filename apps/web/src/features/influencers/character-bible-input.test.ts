import { describe, expect, it } from "vitest";

import { isJsonObject, parseJsonObject, splitList } from "./character-bible-tab";

describe("splitList", () => {
  it("accepts newlines and commas, because both are natural to paste", () => {
    expect(splitList("disciplined\nencouraging")).toEqual(["disciplined", "encouraging"]);
    expect(splitList("disciplined, encouraging")).toEqual(["disciplined", "encouraging"]);
  });

  it("trims and drops blank entries left by trailing separators", () => {
    expect(splitList("  a  ,\n b ,,\n")).toEqual(["a", "b"]);
  });

  it("de-duplicates case-insensitively, matching the backend's rule", () => {
    // The API rejects case-insensitive duplicates with a 422; resolving it here
    // spares the user an error the UI could have prevented.
    expect(splitList("Calm\ncalm\nCALM")).toEqual(["Calm"]);
  });

  it("returns an empty list for empty input", () => {
    expect(splitList(undefined)).toEqual([]);
    expect(splitList("")).toEqual([]);
  });
});

describe("isJsonObject", () => {
  it.each([
    ['{"eye_color":"green"}', true],
    ["{}", true],
    ['["green"]', false],
    ['"green"', false],
    ["42", false],
    ["null", false],
    ["{not json}", false],
  ])("treats %s as object=%s", (raw, expected) => {
    expect(isJsonObject(raw)).toBe(expected);
  });
});

describe("parseJsonObject", () => {
  it("parses a nested object unchanged, so JSONB round-trips exactly", () => {
    expect(parseJsonObject('{"a":{"b":[1,2]}}')).toEqual({ a: { b: [1, 2] } });
  });

  it("returns an empty object for blank input", () => {
    expect(parseJsonObject("")).toEqual({});
    expect(parseJsonObject("   ")).toEqual({});
    expect(parseJsonObject(undefined)).toEqual({});
  });

  it("returns an empty object rather than throwing during a mutation", () => {
    expect(parseJsonObject("[1,2]")).toEqual({});
    expect(parseJsonObject("{broken")).toEqual({});
  });
});
