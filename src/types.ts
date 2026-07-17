export type Tool = "brush" | "rect" | "lasso" | "eraser";
export type Strategy = "fixed" | "moving" | "alpha";
export type TrackingStatus = "idle" | "stale" | "running" | "complete";
export type TaskStatus =
  | "imported"
  | "queued"
  | "exporting"
  | "completed"
  | "cancelled"
  | "failed";

export interface Point {
  x: number;
  y: number;
}

export interface MaskShape {
  id: string;
  kind: "rect" | "lasso" | "brush";
  points: Point[];
  operation: "add" | "subtract";
  brushSize?: number;
}

export interface Keyframe {
  frame: number;
  shapes: MaskShape[];
}

export interface StreamSummary {
  index: number;
  codec: string;
  language?: string;
}

export interface MediaInfo {
  path: string;
  name: string;
  width: number;
  height: number;
  duration: number;
  frameCount: number;
  fps: number;
  pixelFormat: string;
  rotation: number;
  audioStreams: StreamSummary[];
  subtitleStreams: StreamSummary[];
  warnings: string[];
}

export interface TaskEditState {
  strategy: Strategy;
  fixedShapes: MaskShape[];
  shapes: MaskShape[];
  keyframes: Keyframe[];
  trackedMasks: Keyframe[];
  trackingConfidence: number[];
  history: MaskShape[][];
  future: MaskShape[][];
  trackingStatus: TrackingStatus;
  lowConfidenceRanges: [number, number][];
  invalidatedRange?: [number, number];
  currentFrame: number;
  zoom: number;
  timelineScroll: number;
  dilation: number;
  feather: number;
  allowVfrExport: boolean;
}

export interface VideoTask {
  id: string;
  media: MediaInfo;
  status: TaskStatus;
  error?: string;
  jobId?: string;
  output?: string;
  progress?: {
    stage: string;
    frame: number;
    total: number;
    fps: number;
    remainingSeconds?: number;
  };
  edit: TaskEditState;
}

export interface EditorState {
  tasks: VideoTask[];
  activeId?: string;
  tool: Tool;
  compareOriginal: boolean;
  codec: "h264" | "h265";
  crf: number;
  outputFps?: number;
  interpolation: "fast" | "motion";
  repairMode: "quality" | "fast";
}

export interface ResourceStatus {
  root: string;
  ffmpeg: boolean;
  ffprobe: boolean;
  engine: boolean;
  qualityEngine: boolean;
  modelsDirectory: boolean;
  executionMode: "portable" | "development";
  gpuAcceleration: boolean;
  gpuName?: string;
}

export interface GpuStatus {
  compatible: boolean;
  installed: boolean;
  gpuName?: string;
  driverVersion?: string;
  vramMb?: number;
  provider?: string;
  downloadBytes: number;
  downloadedBytes: number;
  requiredFreeBytes: number;
  availableFreeBytes?: number;
  cudaLicenseUrl?: string;
  cudnnLicenseUrl?: string;
  reason?: string;
}

export type GpuInstallStage =
  | "checking"
  | "downloading"
  | "verifying"
  | "installing"
  | "testing"
  | "ready"
  | "paused"
  | "failed";

export interface GpuInstallProgress {
  stage: GpuInstallStage;
  artifact?: string;
  downloadedBytes: number;
  totalBytes: number;
  bytesPerSecond: number;
  remainingSeconds?: number;
  message: string;
}
