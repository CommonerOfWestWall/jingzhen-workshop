import type {
  EditorState,
  Keyframe,
  MaskShape,
  MediaInfo,
  TaskStatus,
  Tool,
  TrackingStatus,
  VideoTask,
} from "./types";

export const initialState: EditorState = {
  tasks: [],
  tool: "brush",
  compareOriginal: false,
  codec: "h264",
  crf: 18,
  interpolation: "fast",
  repairMode: "quality",
};

export type Action =
  | { type: "IMPORT"; media: MediaInfo[] }
  | { type: "RESTORE"; state: EditorState }
  | { type: "SET_ACTIVE"; id: string }
  | { type: "SET_TOOL"; tool: Tool }
  | { type: "SET_FRAME"; frame: number }
  | { type: "SET_ZOOM"; zoom: number }
  | { type: "SET_SCROLL"; scroll: number }
  | { type: "SET_STRATEGY"; strategy: VideoTask["edit"]["strategy"] }
  | { type: "PIN_FIXED_SELECTION" }
  | { type: "CLEAR_FIXED_LAYER" }
  | { type: "SET_MORPHOLOGY"; dilation?: number; feather?: number }
  | { type: "SET_ALLOW_VFR_EXPORT"; value: boolean }
  | { type: "APPLY_FIXED_SELECTION_TO_BATCH"; sourceId: string }
  | { type: "ADD_SHAPE"; shape: MaskShape }
  | { type: "CLEAR_SHAPES" }
  | { type: "UNDO" }
  | { type: "REDO" }
  | { type: "ADD_KEYFRAME" }
  | {
      type: "TRACKING";
      status: TrackingStatus;
      ranges?: [number, number][];
    }
  | {
      type: "APPLY_TRACKING_RESULT";
      masks: Keyframe[];
      confidence: number[];
      ranges: [number, number][];
      anchors: Keyframe[];
      activeRange: [number, number];
    }
  | {
      type: "TASK_STATUS";
      id: string;
      status: TaskStatus;
      jobId?: string;
      output?: string;
      error?: string;
    }
  | { type: "PROGRESS"; jobId: string; progress: VideoTask["progress"] }
  | { type: "COMPARE"; value: boolean }
  | {
      type: "OUTPUT";
      codec?: "h264" | "h265";
      crf?: number;
      outputFps?: number | null;
      interpolation?: EditorState["interpolation"];
      repairMode?: EditorState["repairMode"];
    };

function createTask(media: MediaInfo, index: number): VideoTask {
  return {
    id: `${Date.now()}-${index}-${media.path}`,
    media,
    status: "imported",
    edit: {
      strategy: "fixed",
      fixedShapes: [],
      shapes: [],
      keyframes: [],
      trackedMasks: [],
      trackingConfidence: [],
      history: [],
      future: [],
      trackingStatus: "idle",
      lowConfidenceRanges: [],
      currentFrame: 0,
      zoom: 1,
      timelineScroll: 0,
      dilation: 2,
      feather: 2,
      allowVfrExport:
        media.warnings.length > 0 &&
        media.warnings.every((warning) => warning.includes("可变帧率")),
    },
  };
}

function updateActive(
  state: EditorState,
  update: (task: VideoTask) => VideoTask,
): EditorState {
  if (!state.activeId) return state;
  return {
    ...state,
    tasks: state.tasks.map((task) =>
      task.id === state.activeId ? update(task) : task,
    ),
  };
}

function withShapeEdit(task: VideoTask, shapes: MaskShape[]): VideoTask {
  return {
    ...task,
    edit: {
      ...task.edit,
      history: [...task.edit.history, task.edit.shapes],
      shapes,
      future: [],
      trackingStatus:
        task.edit.trackingStatus === "idle" ? "idle" : "stale",
      trackedMasks: [],
      trackingConfidence: [],
      lowConfidenceRanges: [],
    },
  };
}

function mergeAddRectangle(shapes: MaskShape[], incoming: MaskShape): MaskShape[] {
  if (incoming.kind !== "rect" || incoming.operation !== "add") {
    return [...shapes, incoming];
  }
  let [left, top, right, bottom] = [
    Math.min(incoming.points[0].x, incoming.points[1].x),
    Math.min(incoming.points[0].y, incoming.points[1].y),
    Math.max(incoming.points[0].x, incoming.points[1].x),
    Math.max(incoming.points[0].y, incoming.points[1].y),
  ];
  const remaining: MaskShape[] = [];
  for (const shape of shapes) {
    if (shape.kind !== "rect" || shape.operation !== "add") {
      remaining.push(shape);
      continue;
    }
    const shapeLeft = Math.min(shape.points[0].x, shape.points[1].x);
    const shapeTop = Math.min(shape.points[0].y, shape.points[1].y);
    const shapeRight = Math.max(shape.points[0].x, shape.points[1].x);
    const shapeBottom = Math.max(shape.points[0].y, shape.points[1].y);
    const overlaps =
      left < shapeRight && right > shapeLeft && top < shapeBottom && bottom > shapeTop;
    if (!overlaps) {
      remaining.push(shape);
      continue;
    }
    left = Math.min(left, shapeLeft);
    top = Math.min(top, shapeTop);
    right = Math.max(right, shapeRight);
    bottom = Math.max(bottom, shapeBottom);
  }
  return [
    ...remaining,
    {
      ...incoming,
      points: [
        { x: left, y: top },
        { x: right, y: bottom },
      ],
    },
  ];
}

function affectedTrackingRange(task: VideoTask, frame: number): [number, number] {
  const anchorFrames = task.edit.keyframes
    .map((item) => item.frame)
    .filter((item) => item !== frame)
    .sort((a, b) => a - b);
  const previous = anchorFrames.filter((item) => item < frame).at(-1) ?? 0;
  const next = anchorFrames.find((item) => item > frame) ?? task.media.frameCount - 1;
  return [previous, next];
}

export function isBatchSelectionCompatible(source: VideoTask, target: VideoTask): boolean {
  const sourceRotation = ((source.media.rotation % 360) + 360) % 360;
  const targetRotation = ((target.media.rotation % 360) + 360) % 360;
  return (
    source.media.width === target.media.width &&
    source.media.height === target.media.height &&
    sourceRotation === targetRotation
  );
}

export function editorReducer(state: EditorState, action: Action): EditorState {
  switch (action.type) {
    case "IMPORT": {
      const known = new Set(state.tasks.map((task) => task.media.path));
      const added = action.media
        .filter((media) => !known.has(media.path))
        .map(createTask);
      return {
        ...state,
        tasks: [...state.tasks, ...added],
        activeId: state.activeId ?? added[0]?.id,
      };
    }
    case "RESTORE":
      return {
        ...action.state,
        repairMode: action.state.repairMode ?? "quality",
        tasks: action.state.tasks.map((task) => ({
          ...task,
          edit: {
            ...task.edit,
            fixedShapes: task.edit.fixedShapes ?? [],
            trackedMasks: task.edit.trackedMasks ?? [],
            trackingConfidence: task.edit.trackingConfidence ?? [],
          },
        })),
      };
    case "SET_ACTIVE":
      return state.tasks.some((task) => task.id === action.id)
        ? { ...state, activeId: action.id }
        : state;
    case "SET_TOOL":
      return { ...state, tool: action.tool };
    case "SET_FRAME":
      return updateActive(state, (task) => ({
        ...task,
        edit: {
          ...task.edit,
          currentFrame: Math.max(
            0,
            Math.min(task.media.frameCount - 1, action.frame),
          ),
        },
      }));
    case "SET_ZOOM":
      return updateActive(state, (task) => ({
        ...task,
        edit: { ...task.edit, zoom: Math.max(0.5, Math.min(4, action.zoom)) },
      }));
    case "SET_SCROLL":
      return updateActive(state, (task) => ({
        ...task,
        edit: { ...task.edit, timelineScroll: action.scroll },
      }));
    case "SET_STRATEGY":
      return updateActive(state, (task) => ({
        ...task,
        edit: {
          ...task.edit,
          strategy: action.strategy,
          trackingStatus: task.edit.shapes.length ? "stale" : "idle",
          trackedMasks: [],
          trackingConfidence: [],
          lowConfidenceRanges: [],
        },
      }));
    case "PIN_FIXED_SELECTION":
      return updateActive(state, (task) => {
        if (task.edit.strategy !== "fixed" || !task.edit.shapes.length) return task;
        return {
          ...task,
          edit: {
            ...task.edit,
            strategy: "moving",
            fixedShapes: [
              ...task.edit.fixedShapes,
              ...structuredClone(task.edit.shapes),
            ],
            shapes: [],
            keyframes: [],
            trackedMasks: [],
            trackingConfidence: [],
            history: [],
            future: [],
            trackingStatus: "idle",
            lowConfidenceRanges: [],
          },
        };
      });
    case "CLEAR_FIXED_LAYER":
      return updateActive(state, (task) => ({
        ...task,
        edit: { ...task.edit, fixedShapes: [] },
      }));
    case "SET_MORPHOLOGY":
      return updateActive(state, (task) => ({
        ...task,
        edit: {
          ...task.edit,
          dilation: action.dilation ?? task.edit.dilation,
          feather: action.feather ?? task.edit.feather,
        },
      }));
    case "ADD_SHAPE":
      return updateActive(state, (task) => {
        const trackedBase =
          task.edit.trackingStatus === "complete" &&
          task.edit.strategy !== "fixed"
            ? task.edit.trackedMasks.find(
                (mask) => mask.frame === task.edit.currentFrame,
              )?.shapes
            : undefined;
        const shapes = mergeAddRectangle(
          trackedBase ?? task.edit.shapes,
          action.shape,
        );
        const edited = withShapeEdit(task, shapes);
        if (!trackedBase) return edited;
        const correction: Keyframe = {
          frame: task.edit.currentFrame,
          shapes: structuredClone(shapes),
        };
        return {
          ...edited,
          edit: {
            ...edited.edit,
            trackedMasks: task.edit.trackedMasks,
            trackingConfidence: task.edit.trackingConfidence,
            lowConfidenceRanges: task.edit.lowConfidenceRanges,
            invalidatedRange: affectedTrackingRange(task, correction.frame),
            keyframes: [
              ...task.edit.keyframes.filter(
                (item) => item.frame !== correction.frame,
              ),
              correction,
            ].sort((a, b) => a.frame - b.frame),
          },
        };
      });
    case "CLEAR_SHAPES":
      return updateActive(state, (task) => withShapeEdit(task, []));
    case "UNDO":
      return updateActive(state, (task) => {
        const previous = task.edit.history.at(-1);
        if (!previous) return task;
        return {
          ...task,
          edit: {
            ...task.edit,
            shapes: previous,
            history: task.edit.history.slice(0, -1),
            future: [task.edit.shapes, ...task.edit.future],
            trackingStatus: "stale",
            trackedMasks: [],
            trackingConfidence: [],
            lowConfidenceRanges: [],
          },
        };
      });
    case "SET_ALLOW_VFR_EXPORT":
      return updateActive(state, (task) => ({
        ...task,
        edit: { ...task.edit, allowVfrExport: action.value },
      }));
    case "APPLY_FIXED_SELECTION_TO_BATCH": {
      const source = state.tasks.find((task) => task.id === action.sourceId);
      if (
        !source ||
        !source.edit.shapes.length ||
        !["fixed", "alpha"].includes(source.edit.strategy)
      ) {
        return state;
      }
      return {
        ...state,
        tasks: state.tasks.map((task) => {
          if (
            task.id === source.id ||
            task.status === "exporting" ||
            !isBatchSelectionCompatible(source, task)
          ) {
            return task;
          }
          return {
            ...task,
            status: "imported",
            error: undefined,
            jobId: undefined,
            output: undefined,
            progress: undefined,
            edit: {
              ...task.edit,
              strategy: source.edit.strategy,
              history: [...task.edit.history, task.edit.shapes],
              shapes: structuredClone(source.edit.shapes),
              keyframes: [],
              trackedMasks: [],
              trackingConfidence: [],
              future: [],
              trackingStatus: "complete",
              lowConfidenceRanges: [],
              dilation: source.edit.dilation,
              feather: source.edit.feather,
            },
          };
        }),
      };
    }
    case "REDO":
      return updateActive(state, (task) => {
        const [next, ...future] = task.edit.future;
        if (!next) return task;
        return {
          ...task,
          edit: {
            ...task.edit,
            shapes: next,
            history: [...task.edit.history, task.edit.shapes],
            future,
            trackingStatus: "stale",
            trackedMasks: [],
            trackingConfidence: [],
            lowConfidenceRanges: [],
          },
        };
      });
    case "ADD_KEYFRAME":
      return updateActive(state, (task) => {
        const shapes =
          task.edit.trackingStatus === "complete" && task.edit.strategy !== "fixed"
            ? task.edit.trackedMasks.find(
                (mask) => mask.frame === task.edit.currentFrame,
              )?.shapes ?? task.edit.shapes
            : task.edit.shapes;
        if (!shapes.length) return task;
        const keyframe: Keyframe = {
          frame: task.edit.currentFrame,
          shapes: structuredClone(shapes),
        };
        const preservingTrackedMasks =
          task.edit.trackingStatus === "complete" && task.edit.strategy !== "fixed";
        return {
          ...task,
          edit: {
            ...task.edit,
            keyframes: [
              ...task.edit.keyframes.filter(
                (item) => item.frame !== keyframe.frame,
              ),
              keyframe,
            ].sort((a, b) => a.frame - b.frame),
            shapes: structuredClone(shapes),
            trackedMasks: preservingTrackedMasks ? task.edit.trackedMasks : [],
            trackingConfidence: preservingTrackedMasks
              ? task.edit.trackingConfidence
              : [],
            lowConfidenceRanges: preservingTrackedMasks
              ? task.edit.lowConfidenceRanges
              : [],
            invalidatedRange: preservingTrackedMasks
              ? affectedTrackingRange(task, keyframe.frame)
              : undefined,
            trackingStatus: "stale",
          },
        };
      });
    case "TRACKING":
      return updateActive(state, (task) => ({
        ...task,
        edit: {
          ...task.edit,
          trackingStatus: action.status,
          lowConfidenceRanges: action.ranges ?? task.edit.lowConfidenceRanges,
        },
      }));
    case "APPLY_TRACKING_RESULT":
      return updateActive(state, (task) => {
        const [start, end] = action.activeRange;
        const fullRange = start === 0 && end === task.media.frameCount - 1;
        const trackedMasks = fullRange
          ? action.masks
          : [
              ...task.edit.trackedMasks.filter(
                (mask) => mask.frame < start || mask.frame > end,
              ),
              ...action.masks,
            ].sort((a, b) => a.frame - b.frame);
        const trackingConfidence = fullRange
          ? action.confidence
          : task.edit.trackingConfidence.map((value, frame) =>
              frame >= start && frame <= end
                ? (action.confidence[frame] ?? value)
                : value,
            );
        const lowConfidenceRanges = fullRange
          ? action.ranges
          : [
              ...task.edit.lowConfidenceRanges.filter(
                ([rangeStart, rangeEnd]) => rangeEnd < start || rangeStart > end,
              ),
              ...action.ranges,
            ].sort((a, b) => a[0] - b[0]);
        return {
          ...task,
          edit: {
            ...task.edit,
            trackedMasks,
            trackingConfidence,
            keyframes: action.anchors
              .map((anchor) => structuredClone(anchor))
              .sort((a, b) => a.frame - b.frame),
            trackingStatus: "complete",
            lowConfidenceRanges,
            invalidatedRange: undefined,
          },
        };
      });
    case "TASK_STATUS":
      return {
        ...state,
        tasks: state.tasks.map((task) =>
          task.id === action.id
            ? {
                ...task,
                status: action.status,
                jobId: action.jobId ?? task.jobId,
                output: action.output ?? task.output,
                error: action.error,
                progress: action.status === "queued" ? undefined : task.progress,
              }
            : task,
        ),
      };
    case "PROGRESS":
      return {
        ...state,
        tasks: state.tasks.map((task) =>
          task.jobId === action.jobId
            ? { ...task, progress: action.progress }
            : task,
        ),
      };
    case "COMPARE":
      return { ...state, compareOriginal: action.value };
    case "OUTPUT":
      return {
        ...state,
        codec: action.codec ?? state.codec,
        crf: action.crf ?? state.crf,
        outputFps: action.outputFps === null ? undefined : action.outputFps ?? state.outputFps,
        interpolation: action.interpolation ?? state.interpolation,
        repairMode: action.repairMode ?? state.repairMode,
      };
  }
}

export function hasSelection(task?: VideoTask): boolean {
  return Boolean(
    task &&
      (task.edit.fixedShapes.length ||
        task.edit.shapes.length ||
        task.edit.keyframes.some((keyframe) => keyframe.shapes.length)),
  );
}

export function canExportTask(task?: VideoTask): boolean {
  const vfrOnly = Boolean(
    task?.media.warnings.length &&
      task.media.warnings.every((warning) => warning.includes("可变帧率")),
  );
  return Boolean(
    task &&
      task.edit.trackingStatus === "complete" &&
      (task.media.warnings.length === 0 || (vfrOnly && task.edit.allowVfrExport)) &&
      task.status !== "exporting",
  );
}

export function exportBlockReason(task?: VideoTask): string | undefined {
  if (!task) return "请先导入视频";
  if (task.edit.trackingStatus !== "complete") return "请先标记目标并完成跟踪";
  if (!task.media.warnings.length) return undefined;
  const vfrOnly = task.media.warnings.every((warning) => warning.includes("可变帧率"));
  if (vfrOnly) {
    return task.edit.allowVfrExport
      ? undefined
      : "该视频为可变帧率：勾选下方确认后可按平均帧率导出";
  }
  return task.media.warnings.join("；");
}
