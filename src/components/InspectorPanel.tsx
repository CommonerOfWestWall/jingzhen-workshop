import { AlertTriangle, Check, Download, Gauge, Pause, Sparkles } from "lucide-react";
import { formatBytes, formatRemaining, gpuActionLabel } from "../gpu-component";
import { taskProgressDetail, taskStatusLabel } from "../job-progress";
import type { EditorState, GpuInstallProgress, GpuStatus, ResourceStatus, Strategy, VideoTask } from "../types";

interface Props {
  task?: VideoTask;
  resources?: ResourceStatus;
  gpuStatus?: GpuStatus;
  gpuProgress?: GpuInstallProgress;
  gpuInstalling: boolean;
  codec: EditorState["codec"];
  crf: number;
  outputFps?: number;
  interpolation: EditorState["interpolation"];
  repairMode: EditorState["repairMode"];
  canTrack: boolean;
  canPreview: boolean;
  canExport: boolean;
  previewReady: boolean;
  batchTaskCount: number;
  compatibleBatchCount: number;
  exportBlockReason?: string;
  onStrategy(strategy: Strategy): void;
  onPinFixedSelection(): void;
  onClearFixedLayer(): void;
  onMorphology(dilation?: number, feather?: number): void;
  onAllowVfrExport(value: boolean): void;
  onTrack(): void;
  onPreview(): void;
  onCodec(codec: EditorState["codec"]): void;
  onCrf(crf: number): void;
  onOutputFps(fps?: number): void;
  onInterpolation(value: EditorState["interpolation"]): void;
  onRepairMode(value: EditorState["repairMode"]): void;
  onExport(): void;
  onBatchExport(): void;
  onApplySelectionToBatch(): void;
  onInstallGpu(): void;
  onPauseGpu(): void;
}

const strategyCopy: Record<Strategy, string> = {
  fixed: "同一掩膜应用到全片或指定范围",
  moving: "关键帧之间双向传播并允许修正",
  alpha: "完整覆盖并插值轨迹，避免淡出时跳变",
};

function GpuDeviceSection(props: Pick<Props, "resources" | "gpuStatus" | "gpuProgress" | "gpuInstalling" | "onInstallGpu" | "onPauseGpu">) {
  const status = props.gpuStatus;
  const progress = props.gpuProgress;
  const total = progress?.totalBytes || status?.downloadBytes || 0;
  const downloaded = progress?.downloadedBytes ?? status?.downloadedBytes ?? 0;
  const percent = total ? Math.min(100, Math.round((downloaded / total) * 100)) : 0;
  const diskInsufficient = Boolean(
    status?.availableFreeBytes !== undefined &&
      status.availableFreeBytes < status.requiredFreeBytes,
  );
  return (
    <section className="gpu-section">
      <label className="section-label">处理设备</label>
      <div className={`device-card ${status?.installed ? "gpu-ready" : ""}`}>
        <Gauge size={17} />
        <div>
          <strong>
            {status?.installed
              ? `${status.gpuName ?? "NVIDIA GPU"} 加速`
              : "CPU 模式（可直接使用）"}
          </strong>
          <span>
            {status?.installed
              ? "已通过真实 LaMa 模型自检；预览和导出自动使用 GPU"
              : props.resources?.qualityEngine
                ? "无需安装环境；高清修复可用，但速度较慢"
                : "高清修复资源不完整"}
          </span>
        </div>
      </div>
      {!status?.installed && status?.compatible ? (
        <div className="gpu-installer">
          <div className="gpu-installer-heading">
            <div>
              <strong>{status.gpuName}</strong>
              <span>驱动 {status.driverVersion} · 显存 {Math.round((status.vramMb ?? 0) / 1024)} GB</span>
            </div>
            <span>{formatBytes(status.downloadBytes)}</span>
          </div>
          {progress && !["failed", "ready"].includes(progress.stage) ? (
            <>
              <progress value={downloaded} max={Math.max(1, total)} />
              <div className="gpu-progress-copy">
                <span>{progress.message} · {percent}%</span>
                <span>
                  {progress.bytesPerSecond
                    ? `${formatBytes(progress.bytesPerSecond)}/秒 · ${formatRemaining(progress.remainingSeconds)}`
                    : progress.stage === "paused" ? "进度已保留" : "请稍候"}
                </span>
              </div>
            </>
          ) : null}
          {progress?.stage === "failed" ? <p className="gpu-error">{progress.message}</p> : null}
          {diskInsufficient ? (
            <p className="gpu-error">
              可用空间 {formatBytes(status.availableFreeBytes ?? 0)}，安装至少需要 {formatBytes(status.requiredFreeBytes)}。
            </p>
          ) : null}
          {props.gpuInstalling ? (
            <button className="secondary-button wide" onClick={props.onPauseGpu}>
              <Pause size={14} /> 暂停下载
            </button>
          ) : (
            <button className="secondary-button wide" disabled={diskInsufficient} onClick={props.onInstallGpu}>
              <Download size={14} /> {gpuActionLabel(status, progress)}
            </button>
          )}
          <p className="hint">
            约需 {formatBytes(status.requiredFreeBytes)} 临时空间；安装到当前免安装目录，不修改系统 CUDA。点击安装即表示同意 NVIDIA CUDA/cuDNN 许可。
          </p>
        </div>
      ) : !status?.installed ? (
        <p className="hint">{status?.reason ?? "正在检测 NVIDIA 显卡；CPU 模式不受影响。"}</p>
      ) : null}
      <p className="hint">LaMa 与 ONNX Runtime 允许商业使用；NVIDIA 运行库由用户按其许可从官方源下载。</p>
    </section>
  );
}

export function InspectorPanel(props: Props) {
  const task = props.task;
  const hasSelection = Boolean(
    task &&
      (task.edit.shapes.length || task.edit.keyframes.some((keyframe) => keyframe.shapes.length)),
  );
  const trackingReady = task?.edit.trackingStatus === "complete";
  const vfrOnly = Boolean(
    task?.media.warnings.length &&
      task.media.warnings.every((warning) => warning.includes("可变帧率")),
  );
  const nextAction = !hasSelection
    ? "在画面上框选或涂抹要修复的区域"
    : task?.edit.trackingStatus === "running"
      ? "正在计算掩膜，完成后检查时间轴"
      : !trackingReady
        ? "点击“开始跟踪”计算完整时间范围"
        : vfrOnly && !task?.edit.allowVfrExport
          ? "启用 AI 视频兼容模式后即可预览和导出"
          : vfrOnly
            ? "AI 视频兼容模式已开启；建议先预览，也可直接导出"
          : !props.previewReady
            ? "建议先生成预览片段，也可直接导出"
            : "预览已生成，可导出当前视频";
  return (
    <aside className="inspector panel" aria-label="任务设置">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">当前任务</span>
          <h2>范围与导出</h2>
        </div>
        <span className="task-state-label">{task?.status === "failed" ? "上次导出失败" : "按步骤完成"}</span>
      </div>
      {!task ? (
        <div className="inspector-scroll">
          <div className="inspector-empty">导入视频后显示任务设置</div>
          <GpuDeviceSection {...props} />
        </div>
      ) : (
        <div className="inspector-scroll">
          <div className="workflow-guide">
            <span className="eyebrow">下一步</span>
            <strong>{nextAction}</strong>
            <div className="workflow-steps" aria-label="工作流程">
              {[
                ["标记", hasSelection],
                ["跟踪", trackingReady],
                ["预览", props.previewReady],
                ["导出", task.status === "completed"],
              ].map(([label, done], index) => (
                <span key={String(label)} className={done ? "done" : index === 0 || hasSelection ? "" : "pending"}>
                  {done ? <Check size={10} /> : index + 1} {label}
                </span>
              ))}
            </div>
            {task.status === "failed" && task.error ? (
              <p className="last-error">上次失败：{task.error}</p>
            ) : null}
            {task.status === "exporting" ? (
              <div className={`export-stage-card stage-${task.progress?.stage ?? "prepare"}`} role="status">
                <strong>{taskStatusLabel(task)}</strong>
                <span>{taskProgressDetail(task)}</span>
              </div>
            ) : null}
            {vfrOnly && trackingReady ? (
              <label className="risk-consent compact">
                <input
                  type="checkbox"
                  checked={Boolean(task.edit.allowVfrExport)}
                  onChange={(event) => props.onAllowVfrExport(event.currentTarget.checked)}
                />
                <span>AI 视频兼容模式（推荐）：保留全部帧，按平均帧率重建时间轴</span>
              </label>
            ) : null}
            <div className="workflow-actions">
              {!trackingReady ? (
                <button className="primary-button wide" disabled={!props.canTrack} onClick={props.onTrack}>
                  {task.edit.trackingStatus === "stale" ? "更新跟踪" : "开始跟踪"}
                </button>
              ) : (
                <>
                  <button className="secondary-button" disabled={!props.canPreview} onClick={props.onPreview}>
                    {props.previewReady ? "重新预览" : "生成预览"}
                  </button>
                  <button className="primary-button" disabled={!props.canExport || task.status === "exporting"} onClick={props.onExport}>
                    <Download size={14} /> {task.status === "exporting" ? "导出中" : "导出视频"}
                  </button>
                </>
              )}
            </div>
          </div>
          <section>
            <label className="section-label">范围策略</label>
            <div className="segmented vertical">
              {(["fixed", "moving", "alpha"] as Strategy[]).map((strategy) => (
                <button
                  key={strategy}
                  className={task.edit.strategy === strategy ? "active" : ""}
                  onClick={() => props.onStrategy(strategy)}
                >
                  <strong>
                    {strategy === "fixed" ? "固定区域" : strategy === "moving" ? "移动目标" : "透明度变化"}
                  </strong>
                  <span>{strategyCopy[strategy]}</span>
                </button>
              ))}
            </div>
            {task.edit.strategy === "fixed" && task.edit.shapes.length ? (
              <div className="batch-selection-box">
                <button className="secondary-button wide" onClick={props.onPinFixedSelection}>
                  保留为固定层，再标记移动目标
                </button>
                <p className="hint">适合同时清除左上角固定标记和画面中移动的标记，一次导出完成。</p>
              </div>
            ) : null}
            {task.edit.fixedShapes.length ? (
              <div className="fixed-layer-card">
                <strong>已保留固定层（{task.edit.fixedShapes.length} 个选区）</strong>
                <button className="text-button" onClick={props.onClearFixedLayer}>移除固定层</button>
              </div>
            ) : null}
            {props.batchTaskCount > 1 && ["fixed", "alpha"].includes(task.edit.strategy) ? (
              <div className="batch-selection-box">
                <button
                  className="secondary-button wide"
                  disabled={!hasSelection || props.compatibleBatchCount === 0 || task.status === "exporting"}
                  onClick={props.onApplySelectionToBatch}
                >
                  将当前选区应用到整批
                </button>
                <p className="hint">
                  可应用到 {props.compatibleBatchCount} 个同分辨率、同方向视频；不兼容视频会跳过。
                </p>
              </div>
            ) : null}
          </section>
          <section className="compact-grid">
            <label>
              膨胀 <span>{task.edit.dilation}px</span>
              <input
                type="range"
                min={0}
                max={12}
                value={task.edit.dilation}
                onChange={(event) => props.onMorphology(Number(event.currentTarget.value), undefined)}
              />
            </label>
            <label>
              羽化 <span>{task.edit.feather}px</span>
              <input
                type="range"
                min={0}
                max={12}
                value={task.edit.feather}
                onChange={(event) => props.onMorphology(undefined, Number(event.currentTarget.value))}
              />
            </label>
          </section>
          <section>
            <label className="section-label">跟踪状态</label>
            <div className={`tracking-card tracking-${task.edit.trackingStatus}`}>
              <Sparkles size={17} />
              <div>
                <strong>
                  {task.edit.trackingStatus === "complete"
                    ? "已完成，可检查"
                    : task.edit.trackingStatus === "running"
                      ? "正在计算掩膜"
                      : task.edit.trackingStatus === "stale"
                        ? "修正后需要重算"
                        : "等待选区"}
                </strong>
                <span>
                  {task.edit.lowConfidenceRanges.length
                    ? `${task.edit.lowConfidenceRanges.length} 个低置信度区间`
                    : "低置信度区间会显示在时间轴"}
                </span>
              </div>
            </div>
            {trackingReady ? (
              <button className="text-button wide" disabled={!props.canTrack} onClick={props.onTrack}>
                重新计算跟踪
              </button>
            ) : null}
          </section>
          <section>
            <label className="section-label">修复质量</label>
            <div className="segmented vertical repair-quality">
              <button
                className={props.repairMode === "quality" ? "active" : ""}
                disabled={!props.resources?.qualityEngine}
                onClick={() => props.onRepairMode("quality")}
              >
                <strong>高清修复（推荐）</strong>
                <span>
                  {task.edit.strategy === "moving"
                    ? "按双向跟踪掩膜逐帧重建，避免旧版模糊覆盖"
                    : "LaMa 重建复杂纹理；CPU 实测约 0.9 帧/秒"}
                </span>
              </button>
              <button
                className={props.repairMode === "fast" ? "active" : ""}
                onClick={() => props.onRepairMode("fast")}
              >
                <strong>快速草稿</strong>
                <span>只适合检查选区；复杂背景可能出现模糊色块</span>
              </button>
            </div>
            {!props.resources?.qualityEngine ? (
              <p className="action-explanation">缺少高清修复模型，请使用完整免安装版。</p>
            ) : null}
          </section>
          <GpuDeviceSection {...props} />
          <section>
            <label className="section-label">输出</label>
            <div className="segmented">
              <button className={props.codec === "h264" ? "active" : ""} onClick={() => props.onCodec("h264")}>H.264</button>
              <button className={props.codec === "h265" ? "active" : ""} onClick={() => props.onCodec("h265")}>H.265</button>
            </div>
            <label className="field-row">
              <span>质量 CRF</span>
              <input type="number" min={0} max={51} value={props.crf} onChange={(event) => props.onCrf(Number(event.currentTarget.value))} />
            </label>
            <label className="field-row">
              <span>输出帧率</span>
              <input
                type="number"
                min={1}
                max={120}
                step={0.001}
                placeholder={task.media.fps.toFixed(3)}
                value={props.outputFps ?? ""}
                onChange={(event) => {
                  const value = event.currentTarget.valueAsNumber;
                  props.onOutputFps(Number.isFinite(value) ? value : undefined);
                }}
              />
            </label>
            <p className="hint">留空使用源视频平均帧率 {task.media.fps.toFixed(3)} fps；可输入 24、25、30、60 或 1–120。</p>
            <div className="segmented frame-mode">
              <button className={props.interpolation === "fast" ? "active" : ""} onClick={() => props.onInterpolation("fast")}>
                <strong>快速转换</strong><span>复制/删除少量帧</span>
              </button>
              <button className={props.interpolation === "motion" ? "active" : ""} onClick={() => props.onInterpolation("motion")}>
                <strong>运动补帧</strong><span>生成中间帧，速度较慢</span>
              </button>
            </div>
            <p className="hint">保持原分辨率；音频兼容时复制，字幕使用显式映射。</p>
            {task.media.warnings.length ? (
              <div className="export-blocker">
                <AlertTriangle size={15} />
                <div>
                  <strong>{vfrOnly ? "AI 视频兼容模式" : "当前素材不支持安全导出"}</strong>
                  {task.media.warnings.map((warning) => <p key={warning}>{warning}</p>)}
                </div>
              </div>
            ) : null}
          </section>
          {props.exportBlockReason ? <p className="action-explanation">{props.exportBlockReason}</p> : null}
          <button className="secondary-button wide" disabled={!props.canExport} onClick={props.onBatchExport}>
            批量导出所有就绪视频
          </button>
        </div>
      )}
    </aside>
  );
}
