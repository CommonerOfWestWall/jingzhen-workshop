import type { GpuInstallProgress, GpuStatus } from "./types";

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(0, Math.round(bytes / 1024))} KB`;
}

export function formatRemaining(seconds?: number): string {
  if (!seconds || seconds < 1) return "正在估算";
  if (seconds < 60) return `约 ${Math.ceil(seconds)} 秒`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `约 ${minutes} 分钟`;
  return `约 ${(minutes / 60).toFixed(1)} 小时`;
}

export function gpuActionLabel(status?: GpuStatus, progress?: GpuInstallProgress): string {
  if (status?.installed) return "GPU 加速已启用";
  if (progress?.stage === "paused") return "继续安装";
  if (progress && !["failed", "ready"].includes(progress.stage)) return "安装中";
  return status?.downloadedBytes ? "继续安装" : "安装 NVIDIA GPU 加速";
}
