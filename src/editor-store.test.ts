import { describe, expect, it } from "vitest";
import {
  canExportTask,
  editorReducer,
  exportBlockReason,
  initialState,
  isBatchSelectionCompatible,
} from "./editor-store";
import type { MediaInfo } from "./types";

const media: MediaInfo = {
  path: "C:\\video.mp4",
  name: "video.mp4",
  width: 1920,
  height: 1080,
  duration: 2,
  frameCount: 60,
  fps: 30,
  pixelFormat: "yuv420p",
  rotation: 0,
  audioStreams: [],
  subtitleStreams: [],
  warnings: [],
};

describe("editorReducer", () => {
  it("defaults to high quality and upgrades older saved projects", () => {
    expect(initialState.repairMode).toBe("quality");
    const legacy = { ...initialState, repairMode: undefined } as unknown as typeof initialState;
    const restored = editorReducer(initialState, { type: "RESTORE", state: legacy });
    expect(restored.repairMode).toBe("quality");
  });

  it("preserves timeline state when switching queue items", () => {
    let state = editorReducer(initialState, {
      type: "IMPORT",
      media: [media, { ...media, path: "C:\\second.mp4", name: "second.mp4" }],
    });
    const first = state.activeId!;
    state = editorReducer(state, { type: "SET_FRAME", frame: 42 });
    state = editorReducer(state, { type: "SET_ACTIVE", id: state.tasks[1].id });
    state = editorReducer(state, { type: "SET_ACTIVE", id: first });
    expect(state.tasks[0].edit.currentFrame).toBe(42);
  });

  it("marks tracking stale after a keyframe edit", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    state = editorReducer(state, {
      type: "ADD_SHAPE",
      shape: {
        id: "shape",
        kind: "rect",
        operation: "add",
        points: [
          { x: 0.1, y: 0.1 },
          { x: 0.2, y: 0.2 },
        ],
      },
    });
    state = editorReducer(state, { type: "TRACKING", status: "complete" });
    state = editorReducer(state, { type: "ADD_KEYFRAME" });
    expect(state.tasks[0].edit.trackingStatus).toBe("stale");
  });

  it("applies real tracked masks without moving the timeline or zoom", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    state = editorReducer(state, { type: "SET_FRAME", frame: 31 });
    state = editorReducer(state, { type: "SET_ZOOM", zoom: 1.6 });
    state = editorReducer(state, {
      type: "APPLY_TRACKING_RESULT",
      masks: [
        {
          frame: 31,
          shapes: [
            {
              id: "tracked-31",
              kind: "lasso",
              operation: "add",
              points: [
                { x: 0.7, y: 0.7 },
                { x: 0.8, y: 0.7 },
                { x: 0.8, y: 0.8 },
              ],
            },
          ],
        },
      ],
      confidence: [0.4],
      ranges: [[12, 18]],
      activeRange: [0, 59],
      anchors: [
        {
          frame: 31,
          shapes: [
            {
              id: "source-31",
              kind: "rect",
              operation: "add",
              points: [
                { x: 0.7, y: 0.7 },
                { x: 0.8, y: 0.8 },
              ],
            },
          ],
        },
      ],
    });

    expect(state.tasks[0].edit.trackingStatus).toBe("complete");
    expect(state.tasks[0].edit.trackedMasks).toHaveLength(1);
    expect(state.tasks[0].edit.lowConfidenceRanges).toEqual([[12, 18]]);
    expect(state.tasks[0].edit.currentFrame).toBe(31);
    expect(state.tasks[0].edit.zoom).toBe(1.6);
    expect(state.tasks[0].edit.keyframes.map((item) => item.frame)).toEqual([31]);
  });

  it("keeps a fixed layer while moving selection is tracked", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    state = editorReducer(state, {
      type: "ADD_SHAPE",
      shape: {
        id: "fixed",
        kind: "rect",
        operation: "add",
        points: [
          { x: 0.02, y: 0.02 },
          { x: 0.15, y: 0.1 },
        ],
      },
    });
    state = editorReducer(state, { type: "PIN_FIXED_SELECTION" });

    expect(state.tasks[0].edit.strategy).toBe("moving");
    expect(state.tasks[0].edit.fixedShapes).toHaveLength(1);
    expect(state.tasks[0].edit.shapes).toHaveLength(0);
    expect(state.tasks[0].edit.trackingStatus).toBe("idle");
    expect(canExportTask(state.tasks[0])).toBe(false);
  });

  it("preserves tracked masks outside a corrected keyframe interval", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    state = editorReducer(state, { type: "SET_STRATEGY", strategy: "moving" });
    const trackedShape = {
      id: "tracked",
      kind: "rect" as const,
      operation: "add" as const,
      points: [
        { x: 0.5, y: 0.5 },
        { x: 0.6, y: 0.6 },
      ],
    };
    state = editorReducer(state, {
      type: "APPLY_TRACKING_RESULT",
      masks: [0, 30, 59].map((frame) => ({ frame, shapes: [trackedShape] })),
      confidence: Array(60).fill(0.9),
      ranges: [],
      anchors: [
        { frame: 10, shapes: [trackedShape] },
        { frame: 50, shapes: [trackedShape] },
      ],
      activeRange: [0, 59],
    });
    state = editorReducer(state, { type: "SET_FRAME", frame: 30 });
    state = editorReducer(state, { type: "ADD_KEYFRAME" });
    expect(state.tasks[0].edit.invalidatedRange).toEqual([10, 50]);

    state = editorReducer(state, {
      type: "APPLY_TRACKING_RESULT",
      masks: [{ frame: 30, shapes: [trackedShape] }],
      confidence: Array(60).fill(0).map((value, frame) => (frame === 30 ? 1 : value)),
      ranges: [[32, 33]],
      anchors: state.tasks[0].edit.keyframes,
      activeRange: [10, 50],
    });

    expect(state.tasks[0].edit.trackedMasks.map((mask) => mask.frame)).toEqual([
      0,
      30,
      59,
    ]);
    expect(state.tasks[0].edit.invalidatedRange).toBeUndefined();
  });

  it("merges overlapping additive rectangles into one selection", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    for (const [id, points] of [
      ["one", [{ x: 0.1, y: 0.1 }, { x: 0.3, y: 0.3 }]],
      ["two", [{ x: 0.2, y: 0.2 }, { x: 0.4, y: 0.4 }]],
    ] as const) {
      state = editorReducer(state, {
        type: "ADD_SHAPE",
        shape: { id, kind: "rect", operation: "add", points: [...points] },
      });
    }

    expect(state.tasks[0].edit.shapes).toHaveLength(1);
    expect(state.tasks[0].edit.shapes[0].points).toEqual([
      { x: 0.1, y: 0.1 },
      { x: 0.4, y: 0.4 },
    ]);
  });

  it("clears stale progress before a repeated export", () => {
    let state = editorReducer(initialState, { type: "IMPORT", media: [media] });
    state = editorReducer(state, {
      type: "TASK_STATUS",
      id: state.tasks[0].id,
      status: "exporting",
      jobId: "first",
    });
    state = editorReducer(state, {
      type: "PROGRESS",
      jobId: "first",
      progress: { stage: "repair", frame: 60, total: 60, fps: 30 },
    });
    state = editorReducer(state, {
      type: "TASK_STATUS",
      id: state.tasks[0].id,
      status: "queued",
    });
    expect(state.tasks[0].progress).toBeUndefined();
  });

  it("applies one fixed selection to compatible batch items only", () => {
    const differentSize = { ...media, path: "C:\\small.mp4", width: 1280, height: 720 };
    let state = editorReducer(initialState, {
      type: "IMPORT",
      media: [media, { ...media, path: "C:\\same.mp4" }, differentSize],
    });
    const sourceId = state.tasks[0].id;
    state = editorReducer(state, {
      type: "ADD_SHAPE",
      shape: {
        id: "fixed-shape",
        kind: "rect",
        operation: "add",
        points: [{ x: 0.02, y: 0.02 }, { x: 0.18, y: 0.07 }],
      },
    });
    state = editorReducer(state, { type: "TRACKING", status: "complete" });
    state = editorReducer(state, {
      type: "APPLY_FIXED_SELECTION_TO_BATCH",
      sourceId,
    });

    expect(state.tasks[1].edit.shapes).toEqual(state.tasks[0].edit.shapes);
    expect(state.tasks[1].edit.shapes).not.toBe(state.tasks[0].edit.shapes);
    expect(state.tasks[1].edit.trackingStatus).toBe("complete");
    expect(state.tasks[2].edit.shapes).toEqual([]);
    expect(isBatchSelectionCompatible(state.tasks[0], state.tasks[2])).toBe(false);
  });
});

describe("canExportTask", () => {
  it("enables AI video compatibility mode by default for VFR media", () => {
    const imported = editorReducer(initialState, {
      type: "IMPORT",
      media: [{ ...media, warnings: ["检测到可变帧率，已禁止导出"] }],
    });
    const tracked = editorReducer(imported, { type: "TRACKING", status: "complete" });

    expect(tracked.tasks[0].edit.allowVfrExport).toBe(true);
    expect(canExportTask(tracked.tasks[0])).toBe(true);
    expect(exportBlockReason(tracked.tasks[0])).toBeUndefined();

    const disabled = editorReducer(tracked, {
      type: "SET_ALLOW_VFR_EXPORT",
      value: false,
    });
    expect(canExportTask(disabled.tasks[0])).toBe(false);
    expect(exportBlockReason(disabled.tasks[0])).toContain("勾选");
  });
});
