import { describe, expect, it } from "vitest";
import { taskProgressDetail, taskStatusLabel } from "./job-progress";
import type { VideoTask } from "./types";

function exporting(stage: string, frame = 193, total = 193): VideoTask {
  return {
    id: "task",
    status: "exporting",
    media: {
      path: "C:\\video.mp4",
      name: "video.mp4",
      width: 720,
      height: 1280,
      duration: 8,
      frameCount: total,
      fps: 24,
      pixelFormat: "yuv420p",
      rotation: 0,
      audioStreams: [],
      subtitleStreams: [],
      warnings: [],
    },
    progress: { stage, frame, total, fps: 16, remainingSeconds: 0 },
    edit: {
      strategy: "fixed",
      fixedShapes: [],
      shapes: [],
      keyframes: [],
      trackedMasks: [],
      trackingConfidence: [],
      history: [],
      future: [],
      trackingStatus: "complete",
      lowConfidenceRanges: [],
      currentFrame: 0,
      zoom: 1,
      timelineScroll: 0,
      dilation: 2,
      feather: 2,
      allowVfrExport: true,
    },
  };
}

describe("export progress labels", () => {
  it("does not present a full repair frame count as a completed export", () => {
    const task = exporting("repair");
    expect(taskStatusLabel(task)).toBe("画面修复完成 · 正在进入编码");
    expect(taskProgressDetail(task)).toContain("编码阶段即将开始");
  });

  it("names encoding and final validation as separate stages", () => {
    expect(taskStatusLabel(exporting("encode"))).toBe("正在编码 · 画面修复已完成");
    expect(taskProgressDetail(exporting("encode"))).toContain("帧数不会继续增加");
    expect(taskStatusLabel(exporting("finalize"))).toBe("正在校验输出文件");
  });

  it("explains the one-time high-quality model load", () => {
    expect(taskStatusLabel(exporting("model", 0))).toBe("正在加载高清修复模型");
    expect(taskProgressDetail(exporting("model", 0))).toContain("只加载一次");
  });
});
