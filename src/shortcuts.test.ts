import { describe, expect, it } from "vitest";
import { isImportShortcut } from "./shortcuts";

describe("isImportShortcut", () => {
  it("accepts Ctrl+O and Command+O", () => {
    expect(isImportShortcut({ ctrlKey: true, metaKey: false, key: "o" })).toBe(true);
    expect(isImportShortcut({ ctrlKey: false, metaKey: true, key: "O" })).toBe(true);
  });

  it("rejects plain O and unrelated shortcuts", () => {
    expect(isImportShortcut({ ctrlKey: false, metaKey: false, key: "o" })).toBe(false);
    expect(isImportShortcut({ ctrlKey: true, metaKey: false, key: "p" })).toBe(false);
  });
});
