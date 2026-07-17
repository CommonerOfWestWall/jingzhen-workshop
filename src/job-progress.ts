import type { VideoTask } from "./types";

const settledStatus: Record<Exclude<VideoTask["status"], "exporting">, string> = {
  imported: "待编辑",
  queued: "等待开始",
  completed: "已完成",
  cancelled: "已取消",
  failed: "失败",
};

export function taskStatusLabel(task: VideoTask): string {
  if (task.status !== "exporting") return settledStatus[task.status];
  const progress = task.progress;
  if (!progress) return "正在准备导出";
  if (progress.stage === "model") return "正在加载高清修复模型";
  if (progress.stage === "encode") return "正在编码 · 画面修复已完成";
  if (progress.stage === "finalize") return "正在校验输出文件";
  if (progress.total > 0 && progress.frame >= progress.total) {
    return "画面修复完成 · 正在进入编码";
  }
  return `正在修复画面 · ${progress.frame}/${progress.total}`;
}

export function taskProgressDetail(task: VideoTask): string | undefined {
  if (task.status !== "exporting") return undefined;
  const progress = task.progress;
  if (!progress) return "正在启动本机修复引擎，请稍候。";
  if (progress.stage === "model") {
    return "首次载入 LaMa 模型通常需要数秒；同一任务只加载一次。";
  }
  if (progress.stage === "encode") {
    return "正在压缩视频并写入音频、字幕和元数据；此阶段帧数不会继续增加。";
  }
  if (progress.stage === "finalize") {
    return "编码已经结束，正在检查输出文件是否可读取、时长和流信息是否完整。";
  }
  if (progress.total > 0 && progress.frame >= progress.total) {
    return "全部画面已经修复，编码阶段即将开始。";
  }
  const speed = progress.fps > 0 ? ` · ${progress.fps.toFixed(1)} 帧/秒` : "";
  const remaining =
    progress.remainingSeconds === undefined
      ? ""
      : ` · 预计剩余 ${Math.max(0, Math.ceil(progress.remainingSeconds))} 秒`;
  return `正在处理第 ${progress.frame}/${progress.total} 帧${speed}${remaining}`;
}
