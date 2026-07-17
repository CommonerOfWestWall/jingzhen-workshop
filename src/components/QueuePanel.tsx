import { convertFileSrc } from "@tauri-apps/api/core";
import { Film, FolderOpen, Plus } from "lucide-react";
import { taskStatusLabel } from "../job-progress";
import type { VideoTask } from "../types";

function time(seconds: number): string {
  const value = Math.max(0, Math.round(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

interface Props {
  tasks: VideoTask[];
  activeId?: string;
  onImport(): void;
  onSelect(id: string): void;
  onOpenProject(): void;
}

export function QueuePanel({
  tasks,
  activeId,
  onImport,
  onSelect,
  onOpenProject,
}: Props) {
  return (
    <aside className="queue-panel panel" aria-label="视频队列">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">批量任务</span>
          <h2>视频队列</h2>
        </div>
        <button className="icon-button" title="导入视频" onClick={onImport}>
          <Plus size={17} />
        </button>
      </div>
      {tasks.length === 0 ? (
        <div className="queue-empty">
          <Film size={30} strokeWidth={1.5} />
          <p>尚未导入视频</p>
          <span>支持 MP4、MOV、MKV、AVI</span>
          <button className="primary-button import-focus" onClick={onImport}>
            <Plus size={16} /> 导入视频
          </button>
          <button className="text-button" onClick={onOpenProject}>
            <FolderOpen size={15} /> 打开项目
          </button>
        </div>
      ) : (
        <div className="queue-list">
          {tasks.map((task) => (
            <button
              key={task.id}
              className={`queue-item ${task.id === activeId ? "active" : ""}`}
              onClick={() => onSelect(task.id)}
            >
              <video
                className="queue-thumb"
                src={convertFileSrc(task.media.path)}
                preload="auto"
                muted
              />
              <span className="queue-copy">
                <strong title={task.media.name}>{task.media.name}</strong>
                <small>
                  {time(task.media.duration)} · {task.media.width}×{task.media.height}
                </small>
                <small>{task.media.fps.toFixed(2)} fps</small>
                <span className={`status status-${task.status}`}>
                  {taskStatusLabel(task)}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </aside>
  );
}
