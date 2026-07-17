import { describe, expect, it } from "vitest";
import { formatBytes, formatRemaining, gpuActionLabel } from "./gpu-component";

describe("GPU component copy", () => {
  it("makes large download and remaining time readable", () => {
    expect(formatBytes(2_162_245_136)).toBe("2.0 GB");
    expect(formatRemaining(125)).toBe("约 3 分钟");
  });

  it("uses continue wording when resumable data exists", () => {
    expect(gpuActionLabel({ installed: false, compatible: true, downloadedBytes: 5 } as never)).toBe("继续安装");
    expect(gpuActionLabel(undefined, { stage: "paused" } as never)).toBe("继续安装");
  });
});
