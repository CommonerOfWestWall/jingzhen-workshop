import { useEffect, useRef } from "react";
import type { VideoTask } from "../types";

interface Props {
  task?: VideoTask;
  onFrame(frame: number): void;
  onScroll(scroll: number): void;
}
export function Timeline({ task, onFrame, onScroll }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current && task) {
      scrollRef.current.scrollLeft = task.edit.timelineScroll;
    }
  }, [task?.id]);

  if (!task) {
    return <div className="timeline disabled" aria-label="时间轴" />;
  }
  const percent =
    task.media.frameCount > 1
      ? (task.edit.currentFrame / (task.media.frameCount - 1)) * 100
      : 0;
  return (
    <div
      className="timeline"
      ref={scrollRef}
      onScroll={(event) => onScroll(event.currentTarget.scrollLeft)}
    >
      <div className="timeline-info">
        <span>帧 {task.edit.currentFrame + 1} / {task.media.frameCount}</span>
        <span>{(task.edit.currentFrame / task.media.fps).toFixed(2)}s</span>
      </div>
      <div className="timeline-track">
        <input
          aria-label="当前帧"
          type="range"
          min={0}
          max={Math.max(0, task.media.frameCount - 1)}
          value={task.edit.currentFrame}
          onChange={(event) => onFrame(Number(event.currentTarget.value))}
        />
        <span className="playhead" style={{ left: `${percent}%` }} />
        {task.edit.keyframes.map((keyframe) => (
          <button
            key={keyframe.frame}
            className="keyframe-marker"
            style={{ left: `${(keyframe.frame / Math.max(1, task.media.frameCount - 1)) * 100}%` }}
            title={`关键帧 ${keyframe.frame + 1}`}
            onClick={() => onFrame(keyframe.frame)}
          />
        ))}
        {task.edit.lowConfidenceRanges.map(([start, end]) => (
          <span
            key={`${start}-${end}`}
            className="confidence-warning"
            title={`低置信度：${start + 1}–${end + 1} 帧`}
            style={{
              left: `${(start / Math.max(1, task.media.frameCount - 1)) * 100}%`,
              width: `${((end - start) / Math.max(1, task.media.frameCount - 1)) * 100}%`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
