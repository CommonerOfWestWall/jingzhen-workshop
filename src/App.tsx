import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";
import { FolderOpen, Plus, Save } from "lucide-react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  canExportTask,
  editorReducer,
  exportBlockReason,
  hasSelection,
  initialState,
  isBatchSelectionCompatible,
} from "./editor-store";
import { isImportShortcut } from "./shortcuts";
import { taskProgressDetail, taskStatusLabel } from "./job-progress";
import { EditorToolbar } from "./components/EditorToolbar";
import { InspectorPanel } from "./components/InspectorPanel";
import { QueuePanel } from "./components/QueuePanel";
import { Timeline } from "./components/Timeline";
import { VideoCanvas } from "./components/VideoCanvas";
import type {
  EditorState,
  GpuInstallProgress,
  GpuStatus,
  MediaInfo,
  ResourceStatus,
  VideoTask,
} from "./types";

interface TrackingResult {
  keyframes: Array<{
    frame: number;
    shapes: Array<{
      kind: "rect" | "lasso" | "brush";
      operation: "add" | "subtract";
      brushSize?: number;
      points: [number, number][];
    }>;
  }>;
  trackingConfidence: number[];
  lowConfidenceRanges: [number, number][];
  activeRange: [number, number];
  trackingEngine: string;
}

interface StartExportResult {
  jobId: string;
  output: string;
}

interface PreviewClip {
  output: string;
  startFrame: number;
  endFrame: number;
}

interface JobPayload {
  jobId: string;
  status: "running" | "completed" | "cancelled" | "failed";
  output: string;
  detail?: {
    event?: string;
    stage?: string;
    frame?: number;
    total?: number;
    fps?: number;
    remainingSeconds?: number;
  };
  error?: string;
}

function engineProject(task: VideoTask, includeTrackedMasks = true) {
  const tracked =
    includeTrackedMasks &&
    task.edit.trackingStatus === "complete" &&
    task.edit.strategy !== "fixed"
      ? task.edit.trackedMasks
      : [];
  const savedKeyframes = tracked.length
    ? tracked
    : task.edit.keyframes.length
    ? task.edit.keyframes
    : task.edit.shapes.length
      ? [{ frame: task.edit.strategy === "fixed" ? 0 : task.edit.currentFrame, shapes: task.edit.shapes }]
      : [];
  return {
    version: 1,
    strategy: task.edit.strategy,
    activeRange:
      !includeTrackedMasks && task.edit.invalidatedRange
        ? task.edit.invalidatedRange
        : [0, task.media.frameCount - 1],
    dilation: task.edit.dilation,
    feather: task.edit.feather,
    refineLightOverlay: task.edit.strategy === "alpha",
    lowConfidenceGap: Math.max(8, Math.round(task.media.fps / 2)),
    fixedShapes: task.edit.fixedShapes.map((shape) => ({
      kind: shape.kind,
      operation: shape.operation,
      brushSize: shape.brushSize,
      points: shape.points.map((point) => [point.x, point.y]),
    })),
    keyframes: savedKeyframes.map((keyframe) => ({
      frame: keyframe.frame,
      shapes: keyframe.shapes.map((shape) => ({
        kind: shape.kind,
        operation: shape.operation,
        brushSize: shape.brushSize,
        points: shape.points.map((point) => [point.x, point.y]),
      })),
    })),
  };
}

function activeTask(state: EditorState): VideoTask | undefined {
  return state.tasks.find((task) => task.id === state.activeId);
}

export default function App() {
  const [state, dispatch] = useReducer(editorReducer, initialState);
  const [resources, setResources] = useState<ResourceStatus>();
  const [gpuStatus, setGpuStatus] = useState<GpuStatus>();
  const [gpuProgress, setGpuProgress] = useState<GpuInstallProgress>();
  const [playing, setPlaying] = useState(false);
  const [preview, setPreview] = useState<PreviewClip>();
  const [previewBusy, setPreviewBusy] = useState(false);
  const [notice, setNotice] = useState("所有处理均在本机离线完成");
  const stateRef = useRef(state);
  const pendingBatch = useRef<string[]>([]);
  const batchOutput = useRef<string | undefined>(undefined);
  const startExportRef = useRef<
    ((id: string, outputDir: string) => Promise<void>) | undefined
  >(undefined);
  stateRef.current = state;

  const task = useMemo(() => activeTask(state), [state]);
  const selected = hasSelection(task);
  const trackableSelection = Boolean(
    task &&
      (task.edit.strategy === "fixed"
        ? task.edit.shapes.length
        : task.edit.shapes.length || task.edit.keyframes.length),
  );
  const trackingReady = task?.edit.trackingStatus === "complete";
  const qualityResourceMissing = Boolean(
    task &&
      state.repairMode === "quality" &&
      resources &&
      !resources.qualityEngine,
  );
  const exportReady = canExportTask(task) && !qualityResourceMissing;
  const exportBlockedBy = qualityResourceMissing
    ? "缺少 LaMa 高清修复资源，请重新解压完整免安装版"
    : exportBlockReason(task);
  const exporting = task?.status === "exporting";
  const compatibleBatchCount = task
    ? state.tasks.filter(
        (item) =>
          item.id !== task.id &&
          item.status !== "exporting" &&
          isBatchSelectionCompatible(task, item),
      ).length
    : 0;
  const gpuInstalling = Boolean(
    gpuProgress && !["paused", "failed", "ready"].includes(gpuProgress.stage),
  );

  const refreshDeviceStatus = async () => {
    const [nextResources, nextGpu] = await Promise.all([
      invoke<ResourceStatus>("resource_status"),
      invoke<GpuStatus>("gpu_status"),
    ]);
    setResources(nextResources);
    setGpuStatus(nextGpu);
  };

  useEffect(() => {
    setPreview(undefined);
  }, [task?.id, task?.edit.strategy, task?.edit.fixedShapes, task?.edit.shapes, task?.edit.keyframes, task?.edit.trackedMasks, task?.edit.dilation, task?.edit.feather, state.repairMode]);

  useEffect(() => {
    refreshDeviceStatus()
      .catch((error) => setNotice(`资源检测失败：${String(error)}`));
  }, []);

  useEffect(() => {
    let disposed = false;
    const unlisteners: Array<() => void> = [];
    void Promise.all([
      listen<JobPayload>("job-progress", ({ payload }) => {
        const detail = payload.detail;
        if (detail?.event === "progress") {
          dispatch({
            type: "PROGRESS",
            jobId: payload.jobId,
            progress: {
              stage: detail.stage ?? "repair",
              frame: detail.frame ?? 0,
              total: detail.total ?? 0,
              fps: detail.fps ?? 0,
              remainingSeconds: detail.remainingSeconds,
            },
          });
          const current = stateRef.current.tasks.find(
            (item) => item.jobId === payload.jobId,
          );
          if (current) {
            const progressTask: VideoTask = {
              ...current,
              status: "exporting",
              progress: {
                stage: detail.stage ?? "repair",
                frame: detail.frame ?? 0,
                total: detail.total ?? 0,
                fps: detail.fps ?? 0,
                remainingSeconds: detail.remainingSeconds,
              },
            };
            setNotice(`${taskStatusLabel(progressTask)}：${taskProgressDetail(progressTask)}`);
          }
        }
      }),
      listen<JobPayload>("job-complete", ({ payload }) => {
        if (payload.status === "running") return;
        const current = stateRef.current.tasks.find(
          (item) => item.jobId === payload.jobId,
        );
        if (current) {
          dispatch({
            type: "TASK_STATUS",
            id: current.id,
            status: payload.status,
            output: payload.output,
            error: payload.error,
          });
          setNotice(
            payload.status === "completed"
              ? `已导出：${payload.output}`
              : payload.status === "cancelled"
                ? "任务已在安全分段边界取消"
                : `任务失败：${payload.error || "未知错误"}`,
          );
        }
        const next = pendingBatch.current.shift();
        const outputDir = batchOutput.current;
        if (next && outputDir) void startExportRef.current?.(next, outputDir);
      }),
      listen<{ stage: string; frame: number; total: number }>(
        "tracking-progress",
        ({ payload }) => {
          const percent = Math.round(
            (payload.frame / Math.max(1, payload.total)) * 100,
          );
          const stage = payload.stage === "backward" ? "反向核对" : "向前跟踪";
          setNotice(`正在${stage}：${percent}%（${payload.frame}/${payload.total} 个处理单元）`);
        },
      ),
      listen<GpuInstallProgress>("gpu-install-progress", ({ payload }) => {
        setGpuProgress(payload);
        setNotice(payload.message);
      }),
    ]).then((items) => {
      if (disposed) items.forEach((unlisten) => unlisten());
      else unlisteners.push(...items);
    });
    return () => {
      disposed = true;
      unlisteners.forEach((unlisten) => unlisten());
    };
  }, []);

  const installGpu = async () => {
    try {
      setNotice("正在准备 NVIDIA GPU 加速组件…");
      const status = await invoke<GpuStatus>("install_gpu_component");
      setGpuStatus(status);
      if (status.installed) {
        await refreshDeviceStatus();
        setNotice(`${status.gpuName ?? "NVIDIA GPU"} 加速已启用，后续任务将自动使用`);
      }
    } catch (error) {
      const message = String(error);
      setGpuProgress((current) => ({
        stage: "failed",
        downloadedBytes: current?.downloadedBytes ?? gpuStatus?.downloadedBytes ?? 0,
        totalBytes: current?.totalBytes ?? gpuStatus?.downloadBytes ?? 0,
        bytesPerSecond: 0,
        message,
      }));
      setNotice(`GPU 组件安装失败：${message}；CPU 模式不受影响`);
      void refreshDeviceStatus();
    }
  };

  const pauseGpu = async () => {
    await invoke("pause_gpu_install");
    setNotice("将在当前下载数据块写入后暂停并保留进度");
  };

  const importVideos = async () => {
    const selectedPaths = await open({
      multiple: true,
      directory: false,
      filters: [
        { name: "视频", extensions: ["mp4", "mov", "mkv", "avi", "webm", "m4v"] },
      ],
    });
    if (!selectedPaths) return;
    const paths = Array.isArray(selectedPaths) ? selectedPaths : [selectedPaths];
    try {
      setNotice("正在读取视频信息…");
      const media = await invoke<MediaInfo[]>("probe_videos", { paths });
      dispatch({ type: "IMPORT", media });
      setNotice(`已导入 ${media.length} 个视频`);
    } catch (error) {
      setNotice(`导入失败：${String(error)}`);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isImportShortcut(event)) return;
      event.preventDefault();
      void importVideos();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const analyzeTracking = async () => {
    if (!task || !selected) return;
    if (task.edit.strategy === "fixed") {
      dispatch({ type: "TRACKING", status: "complete", ranges: [] });
      setNotice("固定区域已就绪，可生成预览或直接导出");
      return;
    }
    const trackingAnchors = task.edit.keyframes.length
      ? structuredClone(task.edit.keyframes)
      : task.edit.shapes.length
        ? [{ frame: task.edit.currentFrame, shapes: structuredClone(task.edit.shapes) }]
        : [];
    if (!trackingAnchors.length) {
      setNotice("固定层已保留；请再框选需要移动跟踪的目标");
      return;
    }
    dispatch({ type: "TRACKING", status: "running" });
    setNotice("正在准备视频帧并进行双向运动跟踪…");
    try {
      const result = await invoke<TrackingResult>("track_video", {
        request: {
          input: task.media.path,
          project: engineProject(task, false),
        },
      });
      dispatch({
        type: "APPLY_TRACKING_RESULT",
        masks: result.keyframes.map((keyframe) => ({
          frame: keyframe.frame,
          shapes: keyframe.shapes.map((shape, index) => ({
            id: `tracked-${keyframe.frame}-${index}`,
            kind: shape.kind,
            operation: shape.operation,
            brushSize: shape.brushSize,
            points: shape.points.map(([x, y]) => ({ x, y })),
          })),
        })),
        confidence: result.trackingConfidence,
        ranges: result.lowConfidenceRanges,
        anchors: trackingAnchors,
        activeRange: result.activeRange,
      });
      setNotice(
        result.lowConfidenceRanges.length
          ? `双向跟踪完成；黄色时间段有 ${result.lowConfidenceRanges.length} 个低置信度区间，请定位后重新框选修正`
          : "双向跟踪完成；未发现低置信度区间，可以预览检查",
      );
    } catch (error) {
      dispatch({ type: "TRACKING", status: "stale" });
      setNotice(`跟踪失败：${String(error)}`);
    }
  };

  const startExportFor = async (id: string, outputDir: string) => {
    const current = stateRef.current.tasks.find((item) => item.id === id);
    if (!current || !canExportTask(current)) {
      if (current?.media.warnings.length) {
        setNotice(`无法导出：${current.media.warnings.join("；")}`);
      }
      return;
    }
    dispatch({ type: "TASK_STATUS", id, status: "queued" });
    try {
      const result = await invoke<StartExportResult>("start_export", {
        request: {
          input: current.media.path,
          outputDir,
          project: engineProject(current),
          codec: stateRef.current.codec,
          crf: stateRef.current.crf,
          allowUnsafe: current.edit.allowVfrExport,
          targetFps: stateRef.current.outputFps,
          interpolation: stateRef.current.interpolation ?? "fast",
          repairMode: stateRef.current.repairMode ?? "quality",
        },
      });
      dispatch({
        type: "TASK_STATUS",
        id,
        status: "exporting",
        jobId: result.jobId,
        output: result.output,
      });
      setNotice(`开始导出：${current.media.name}`);
    } catch (error) {
      dispatch({
        type: "TASK_STATUS",
        id,
        status: "failed",
        error: String(error),
      });
      setNotice(`无法启动导出：${String(error)}`);
      const next = pendingBatch.current.shift();
      if (next && batchOutput.current)
        void startExportRef.current?.(next, batchOutput.current);
    }
  };
  startExportRef.current = startExportFor;

  const chooseOutputDirectory = async (): Promise<string | undefined> => {
    const directory = await open({ directory: true, multiple: false });
    return typeof directory === "string" ? directory : undefined;
  };

  const exportCurrent = async () => {
    if (!task || !exportReady) {
      if (task?.media.warnings.length) {
        setNotice(`无法导出：${task.media.warnings.join("；")}`);
      }
      return;
    }
    const directory = await chooseOutputDirectory();
    if (directory) await startExportFor(task.id, directory);
  };

  const batchExport = async () => {
    const ready = state.tasks.filter(canExportTask);
    if (!ready.length) return;
    const directory = await chooseOutputDirectory();
    if (!directory) return;
    batchOutput.current = directory;
    pendingBatch.current = ready.slice(1).map((item) => item.id);
    await startExportFor(ready[0].id, directory);
  };

  const applySelectionToBatch = () => {
    if (!task || !selected || !["fixed", "alpha"].includes(task.edit.strategy)) return;
    const compatible = state.tasks.filter(
      (item) =>
        item.id !== task.id &&
        item.status !== "exporting" &&
        isBatchSelectionCompatible(task, item),
    ).length;
    const skipped = Math.max(0, state.tasks.length - 1 - compatible);
    dispatch({ type: "APPLY_FIXED_SELECTION_TO_BATCH", sourceId: task.id });
    setNotice(
      skipped
        ? `已将固定选区应用到 ${compatible} 个视频；跳过 ${skipped} 个尺寸或方向不兼容的视频`
        : `已将固定选区应用到其余 ${compatible} 个视频，现在可以批量导出`,
    );
  };

  const cancelCurrent = async () => {
    if (!task?.jobId) return;
    try {
      await invoke("cancel_job", { jobId: task.jobId });
      setNotice("已请求取消；将在当前安全处理单元完成后停止");
    } catch (error) {
      setNotice(`取消失败：${String(error)}`);
    }
  };

  const createPreview = async () => {
    if (!task || !trackingReady || previewBusy) return;
    setPlaying(false);
    setPreviewBusy(true);
    setNotice("正在离线生成当前位置前后约 3 秒的修复预览…");
    try {
      const result = await invoke<PreviewClip>("create_preview", {
        request: {
          input: task.media.path,
          project: engineProject(task),
          currentFrame: task.edit.currentFrame,
          frameCount: task.media.frameCount,
          fps: task.media.fps,
          repairMode: state.repairMode ?? "quality",
        },
      });
      setPreview(result);
      dispatch({ type: "COMPARE", value: false });
      setNotice(`修复预览已生成：第 ${result.startFrame + 1}–${result.endFrame + 1} 帧`);
      setPlaying(true);
    } catch (error) {
      setNotice(`预览失败：${String(error)}`);
    } finally {
      setPreviewBusy(false);
    }
  };

  const activateTool = (tool: EditorState["tool"]) => {
    setPlaying(false);
    setPreview(undefined);
    dispatch({ type: "COMPARE", value: false });
    dispatch({ type: "SET_TOOL", tool });
  };

  const saveProject = async () => {
    if (!state.tasks.length) return;
    const path = await save({
      defaultPath: "净帧工坊项目.jzf",
      filters: [{ name: "净帧工坊项目", extensions: ["jzf"] }],
    });
    if (!path) return;
    try {
      await invoke("save_project", {
        path,
        project: { version: 1, kind: "workspace", state },
      });
      setNotice(`项目已保存：${path}`);
    } catch (error) {
      setNotice(`保存失败：${String(error)}`);
    }
  };

  const openProject = async () => {
    const path = await open({
      multiple: false,
      directory: false,
      filters: [{ name: "净帧工坊项目", extensions: ["jzf"] }],
    });
    if (typeof path !== "string") return;
    try {
      const project = await invoke<{ version: number; kind: string; state: EditorState }>(
        "load_project",
        { path },
      );
      if (project.kind !== "workspace" || !project.state?.tasks) {
        throw new Error("不是工作区项目");
      }
      dispatch({ type: "RESTORE", state: project.state });
      setNotice(`已打开项目：${path}`);
    } catch (error) {
      setNotice(`打开失败：${String(error)}`);
    }
  };

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand">
          <img src="/app-icon.svg" alt="" />
          <div><h1>净帧工坊</h1><span>离线视频画面修复</span></div>
        </div>
        <div className="header-actions">
          <button className="text-button" onClick={openProject}><FolderOpen size={15} />打开项目</button>
          <button
            className="text-button"
            title="保存当前选区、关键帧和导出设置，下次继续编辑"
            disabled={!state.tasks.length}
            onClick={saveProject}
          ><Save size={15} />保存进度</button>
          <button className="primary-button compact" autoFocus onClick={importVideos}><Plus size={15} />导入视频</button>
        </div>
      </header>
      <div className="workspace-grid">
        <QueuePanel tasks={state.tasks} activeId={state.activeId} onImport={importVideos} onSelect={(id) => { setPlaying(false); dispatch({ type: "SET_ACTIVE", id }); }} onOpenProject={openProject} />
        <section className="editor panel" aria-label="视频编辑器">
          <EditorToolbar
            enabled={Boolean(task)}
            hasSelection={selected}
            trackingReady={trackingReady}
            canExport={exportReady}
            exportBlockReason={exportBlockedBy}
            exporting={Boolean(exporting)}
            tool={state.tool}
            playing={playing}
            comparing={state.compareOriginal}
            canUndo={Boolean(task?.edit.history.length)}
            canRedo={Boolean(task?.edit.future.length)}
            onTool={activateTool}
            onClear={() => dispatch({ type: "CLEAR_SHAPES" })}
            onUndo={() => dispatch({ type: "UNDO" })}
            onRedo={() => dispatch({ type: "REDO" })}
            onKeyframe={() => dispatch({ type: "ADD_KEYFRAME" })}
            onTrack={analyzeTracking}
            onPlay={() => setPlaying((value) => !value)}
            onCompare={() => dispatch({ type: "COMPARE", value: !state.compareOriginal })}
            onFit={() => dispatch({ type: "SET_ZOOM", zoom: 1 })}
            onExport={exportCurrent}
            onCancel={cancelCurrent}
          />
          <VideoCanvas
            task={task}
            tool={state.tool}
            playing={playing}
            compareOriginal={state.compareOriginal}
            preview={preview ? { path: preview.output, startFrame: preview.startFrame, endFrame: preview.endFrame } : undefined}
            onFrame={(frame) => dispatch({ type: "SET_FRAME", frame })}
            onPlaying={setPlaying}
            onShape={(shape) => dispatch({ type: "ADD_SHAPE", shape })}
          />
          <Timeline
            task={task}
            onFrame={(frame) => dispatch({ type: "SET_FRAME", frame })}
            onScroll={(scroll) => dispatch({ type: "SET_SCROLL", scroll })}
          />
        </section>
        <InspectorPanel
          task={task}
          resources={resources}
          gpuStatus={gpuStatus}
          gpuProgress={gpuProgress}
          gpuInstalling={gpuInstalling}
          codec={state.codec}
          crf={state.crf}
          outputFps={state.outputFps}
          interpolation={state.interpolation ?? "fast"}
          repairMode={state.repairMode ?? "quality"}
          canTrack={trackableSelection && task?.edit.trackingStatus !== "running"}
          canPreview={Boolean(trackingReady)}
          canExport={exportReady}
          previewReady={Boolean(preview)}
          batchTaskCount={state.tasks.length}
          compatibleBatchCount={compatibleBatchCount}
          exportBlockReason={exportBlockedBy}
          onStrategy={(strategy) => dispatch({ type: "SET_STRATEGY", strategy })}
          onPinFixedSelection={() => dispatch({ type: "PIN_FIXED_SELECTION" })}
          onClearFixedLayer={() => dispatch({ type: "CLEAR_FIXED_LAYER" })}
          onMorphology={(dilation, feather) => dispatch({ type: "SET_MORPHOLOGY", dilation, feather })}
          onAllowVfrExport={(value) => dispatch({ type: "SET_ALLOW_VFR_EXPORT", value })}
          onTrack={analyzeTracking}
          onPreview={createPreview}
          onCodec={(codec) => dispatch({ type: "OUTPUT", codec })}
          onCrf={(crf) => dispatch({ type: "OUTPUT", crf })}
          onOutputFps={(outputFps) => dispatch({ type: "OUTPUT", outputFps: outputFps ?? null })}
          onInterpolation={(interpolation) => dispatch({ type: "OUTPUT", interpolation })}
          onRepairMode={(repairMode) => dispatch({ type: "OUTPUT", repairMode })}
          onExport={exportCurrent}
          onBatchExport={batchExport}
          onApplySelectionToBatch={applySelectionToBatch}
          onInstallGpu={installGpu}
          onPauseGpu={pauseGpu}
        />
      </div>
      <footer className="status-bar">
        <span className="status-dot" />
        <span>{notice}</span>
        <span className="status-spacer" />
        <span>{resources?.executionMode === "portable" ? "免安装资源" : "开发资源"}</span>
      </footer>
    </main>
  );
}
