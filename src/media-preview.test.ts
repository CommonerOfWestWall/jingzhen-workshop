import { describe, expect, it } from "vitest";
import { displayDimensions, fitContainedDimensions } from "./media-preview";

describe("displayDimensions", () => {
  it("keeps a 720x1280 portrait video portrait", () => {
    expect(displayDimensions({ width: 720, height: 1280, rotation: 0 })).toEqual({
      width: 720,
      height: 1280,
    });
  });

  it("swaps coded dimensions for quarter-turn rotation metadata", () => {
    expect(displayDimensions({ width: 1920, height: 1080, rotation: -90 })).toEqual({
      width: 1080,
      height: 1920,
    });
  });
});

describe("fitContainedDimensions", () => {
  it("fits portrait media without leaving a wider selection surface", () => {
    expect(
      fitContainedDimensions(
        { width: 720, height: 1280 },
        { width: 970, height: 750 },
      ),
    ).toEqual({ width: 421, height: 750 });
  });

  it("fits landscape media by width", () => {
    expect(
      fitContainedDimensions(
        { width: 1920, height: 1080 },
        { width: 960, height: 700 },
      ),
    ).toEqual({ width: 960, height: 540 });
  });
});
