import { convertFileSrc } from "@tauri-apps/api/core";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { displayDimensions, fitContainedDimensions } from "../media-preview";
import type { MaskShape, Point, Tool, VideoTask } from "../types";

interface Props {
  task?: VideoTask;
  tool: Tool;
  playing: boolean;
  compareOriginal: boolean;
  preview?: { path: string; startFrame: number; endFrame: number };
  onFrame(frame: number): void;
  onPlaying(value: boolean): void;
  onShape(shape: MaskShape): void;
}

function pathPoints(points: Point[]): string {
  return points.map((point) => `${point.x * 100},${point.y * 100}`).join(" ");
}

function ShapeView({ shape, draft = false }: { shape: MaskShape; draft?: boolean }) {
  const className = `${shape.operation === "subtract" ? "mask-subtract" : "mask-add"} ${draft ? "draft" : ""}`;
  if (shape.kind === "rect" && shape.points.length >= 2) {
    const [start, end] = shape.points;
    return (
      <rect
        className={className}
        x={Math.min(start.x, end.x) * 100}
        y={Math.min(start.y, end.y) * 100}
        width={Math.abs(end.x - start.x) * 100}
        height={Math.abs(end.y - start.y) * 100}
      />
    );
  }
  const Component = shape.kind === "lasso" ? "polygon" : "polyline";
  return (
    <Component
      className={className}
      points={pathPoints(shape.points)}
      strokeWidth={shape.kind === "brush" ? (shape.brushSize ?? 0.02) * 100 : 0.45}
    />
  );
}

function MaskGeometry({ shape }: { shape: MaskShape }) {
  const color = shape.operation === "subtract" ? "black" : "white";
  if (shape.kind === "rect" && shape.points.length >= 2) {
    const [start, end] = shape.points;
    return (
      <rect
        x={Math.min(start.x, end.x) * 100}
        y={Math.min(start.y, end.y) * 100}
        width={Math.abs(end.x - start.x) * 100}
        height={Math.abs(end.y - start.y) * 100}
        fill={color}
      />
    );
  }
  if (shape.kind === "lasso") {
    return <polygon points={pathPoints(shape.points)} fill={color} />;
  }
  return (
    <polyline
      points={pathPoints(shape.points)}
      fill="none"
      stroke={color}
      strokeWidth={(shape.brushSize ?? 0.02) * 100}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  );
}

export function VideoCanvas({
  task,
  tool,
  playing,
  compareOriginal,
  preview,
  onFrame,
  onPlaying,
  onShape,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const overlayRef = useRef<SVGSVGElement>(null);
  const maskId = useId().replaceAll(":", "");
  const [draft, setDraft] = useState<MaskShape>();
  const [loadError, setLoadError] = useState<string>();
  const [mediaReady, setMediaReady] = useState(false);
  const previewActive = Boolean(preview && !compareOriginal);
  const dimensions = task ? displayDimensions(task.media) : undefined;
  const visibleShapes = useMemo(() => {
    if (!task) return [];
    if (task.edit.trackingStatus === "complete" && task.edit.strategy !== "fixed") {
      return [
        ...task.edit.fixedShapes,
        ...(
        task.edit.trackedMasks.find(
          (mask) => mask.frame === task.edit.currentFrame,
        )?.shapes ?? task.edit.shapes),
      ];
    }
    return [...task.edit.fixedShapes, ...task.edit.shapes];
  }, [
    task?.edit.currentFrame,
    task?.edit.fixedShapes,
    task?.edit.shapes,
    task?.edit.strategy,
    task?.edit.trackedMasks,
    task?.edit.trackingStatus,
    task?.id,
  ]);
  const [surfaceDimensions, setSurfaceDimensions] = useState<
    { width: number; height: number } | undefined
  >();
  const source = useMemo(() => {
    const path = previewActive ? preview?.path : task?.media.path;
    return path ? convertFileSrc(path) : undefined;
  }, [preview?.path, previewActive, task?.media.path]);

  useEffect(() => {
    setLoadError(undefined);
    setMediaReady(false);
  }, [source]);

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage || !dimensions) {
      setSurfaceDimensions(undefined);
      return;
    }
    const resize = () => {
      const bounds = stage.getBoundingClientRect();
      setSurfaceDimensions(
        fitContainedDimensions(dimensions, {
          width: bounds.width * 0.94,
          height: bounds.height * 0.92,
        }),
      );
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(stage);
    return () => observer.disconnect();
  }, [dimensions?.height, dimensions?.width]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !task) return;
    const target = previewActive
      ? Math.max(0, task.edit.currentFrame - (preview?.startFrame ?? 0)) / task.media.fps
      : task.edit.currentFrame / task.media.fps;
    if (Math.abs(video.currentTime - target) > 1 / task.media.fps) {
      video.currentTime = target;
    }
  }, [preview?.startFrame, previewActive, task?.id, task?.edit.currentFrame, task?.media.fps]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      void video.play().catch((error) => {
        setLoadError(`播放失败：${String(error)}`);
        onPlaying(false);
      });
    }
    else video.pause();
  }, [onPlaying, playing]);

  const point = (event: React.PointerEvent<SVGSVGElement>): Point => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  };

  const begin = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!task) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const start = point(event);
    setDraft({
      id: crypto.randomUUID(),
      kind: tool === "rect" ? "rect" : tool === "lasso" ? "lasso" : "brush",
      operation: tool === "eraser" ? "subtract" : "add",
      points: [start, start],
      brushSize: 0.025,
    });
  };

  const move = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!draft) return;
    const next = point(event);
    setDraft({
      ...draft,
      points:
        draft.kind === "rect"
          ? [draft.points[0], next]
          : [...draft.points, next],
    });
  };

  const finish = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!draft) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (draft.points.length >= 2) onShape(draft);
    setDraft(undefined);
  };

  if (!task) {
    return (
      <div className="canvas-empty">
        <div className="empty-frame" />
        <p>导入视频后在这里标记需要修复的区域</p>
      </div>
    );
  }

  return (
    <div ref={stageRef} className="canvas-stage">
      <div
        className="video-surface"
        style={{
          width: surfaceDimensions?.width,
          height: surfaceDimensions?.height,
          visibility: surfaceDimensions ? "visible" : "hidden",
          transform: `scale(${task.edit.zoom})`,
        }}
      >
        <video
          ref={videoRef}
          key={source}
          src={source}
          width={dimensions?.width}
          height={dimensions?.height}
          preload="auto"
          onLoadedMetadata={(event) => {
            event.currentTarget.currentTime = previewActive
              ? Math.max(0, task.edit.currentFrame - (preview?.startFrame ?? 0)) / task.media.fps
              : task.edit.currentFrame / task.media.fps;
          }}
          onLoadedData={() => {
            setMediaReady(true);
            setLoadError(undefined);
          }}
          onError={(event) => {
            const mediaError = event.currentTarget.error;
            const detail = mediaError?.message || `错误代码 ${mediaError?.code ?? "未知"}`;
            setMediaReady(false);
            setLoadError(`无法解码视频预览：${detail}`);
            onPlaying(false);
          }}
          onTimeUpdate={(event) => {
            const offset = previewActive ? (preview?.startFrame ?? 0) : 0;
            onFrame(offset + Math.round(event.currentTarget.currentTime * task.media.fps));
          }}
          onPlay={() => onPlaying(true)}
          onPause={() => onPlaying(false)}
          onEnded={() => onPlaying(false)}
        />
        {!mediaReady ? (
          <div className={`video-load-state ${loadError ? "error" : ""}`} role="status">
            <strong>{loadError ? "预览加载失败" : "正在解码首帧…"}</strong>
            <span>{loadError ?? `${dimensions?.width}×${dimensions?.height}`}</span>
          </div>
        ) : null}
        <svg
          ref={overlayRef}
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className={`mask-overlay ${compareOriginal || previewActive || !mediaReady ? "hidden" : ""}`}
          onPointerDown={begin}
          onPointerMove={move}
          onPointerUp={finish}
          onPointerCancel={() => setDraft(undefined)}
        >
          <defs>
            <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
              <rect x="0" y="0" width="100" height="100" fill="black" />
              {visibleShapes.map((shape) => (
                <MaskGeometry key={shape.id} shape={shape} />
              ))}
            </mask>
          </defs>
          <rect
            className="mask-composite"
            x="0"
            y="0"
            width="100"
            height="100"
            mask={`url(#${maskId})`}
          />
          {visibleShapes.map((shape) => (
            <ShapeView key={shape.id} shape={shape} />
          ))}
          {draft ? <ShapeView shape={draft} draft /> : null}
        </svg>
      </div>
      <span className="canvas-badge">
        {preview ? (compareOriginal ? "原片" : "修复预览") : compareOriginal ? "原片" : "掩膜叠加"}
      </span>
    </div>
  );
}
