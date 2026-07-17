import {
  DiamondPlus,
  Download,
  Eraser,
  Eye,
  Lasso,
  Paintbrush,
  Pause,
  Play,
  Redo2,
  Scan,
  Square,
  SquareDashed,
  SquareX,
  StepBack,
  StepForward,
  Undo2,
} from "lucide-react";
import type { Tool } from "../types";

interface Props {
  enabled: boolean;
  hasSelection: boolean;
  trackingReady: boolean;
  canExport: boolean;
  exportBlockReason?: string;
  exporting: boolean;
  tool: Tool;
  playing: boolean;
  comparing: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onTool(tool: Tool): void;
  onClear(): void;
  onUndo(): void;
  onRedo(): void;
  onKeyframe(): void;
  onTrack(direction: "forward" | "backward"): void;
  onPlay(): void;
  onCompare(): void;
  onFit(): void;
  onExport(): void;
  onCancel(): void;
}

function ToolButton({
  title,
  active = false,
  blocked = false,
  disabled = false,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  blocked?: boolean;
  disabled?: boolean;
  onClick(): void;
  children: React.ReactNode;
}) {
  return (
    <button
      className={`tool-button ${active ? "active" : ""} ${blocked ? "blocked" : ""}`}
      title={title}
      aria-label={title}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function EditorToolbar(props: Props) {
  return (
    <div className="editor-toolbar" role="toolbar" aria-label="编辑工具">
      <div className="tool-group">
        <ToolButton
          title="画笔"
          active={props.tool === "brush"}
          disabled={!props.enabled}
          onClick={() => props.onTool("brush")}
        >
          <Paintbrush size={17} />
        </ToolButton>
        <ToolButton
          title="矩形"
          active={props.tool === "rect"}
          disabled={!props.enabled}
          onClick={() => props.onTool("rect")}
        >
          <SquareDashed size={17} />
        </ToolButton>
        <ToolButton
          title="套索"
          active={props.tool === "lasso"}
          disabled={!props.enabled}
          onClick={() => props.onTool("lasso")}
        >
          <Lasso size={17} />
        </ToolButton>
        <ToolButton
          title="从选区减去"
          active={props.tool === "eraser"}
          disabled={!props.enabled}
          onClick={() => props.onTool("eraser")}
        >
          <Eraser size={17} />
        </ToolButton>
        <ToolButton title="清空选区" disabled={!props.hasSelection} onClick={props.onClear}>
          <SquareX size={17} />
        </ToolButton>
      </div>
      <div className="tool-group">
        <ToolButton title="撤销" disabled={!props.canUndo} onClick={props.onUndo}>
          <Undo2 size={17} />
        </ToolButton>
        <ToolButton title="重做" disabled={!props.canRedo} onClick={props.onRedo}>
          <Redo2 size={17} />
        </ToolButton>
        <ToolButton title="添加关键帧" disabled={!props.hasSelection} onClick={props.onKeyframe}>
          <DiamondPlus size={17} />
        </ToolButton>
      </div>
      <div className="tool-group">
        <ToolButton title="向后跟踪" disabled={!props.hasSelection} onClick={() => props.onTrack("backward")}>
          <StepBack size={17} />
        </ToolButton>
        <ToolButton title="向前跟踪" disabled={!props.hasSelection} onClick={() => props.onTrack("forward")}>
          <StepForward size={17} />
        </ToolButton>
      </div>
      <div className="tool-group push-right">
        <ToolButton title={props.playing ? "暂停" : "播放"} disabled={!props.enabled} onClick={props.onPlay}>
          {props.playing ? <Pause size={17} /> : <Play size={17} />}
        </ToolButton>
        <ToolButton title="前后对比" active={props.comparing} disabled={!props.trackingReady} onClick={props.onCompare}>
          <Eye size={17} />
        </ToolButton>
        <ToolButton title="适合窗口" disabled={!props.enabled} onClick={props.onFit}>
          <Scan size={17} />
        </ToolButton>
        <ToolButton
          title={props.canExport ? "导出" : props.exportBlockReason ?? "导出"}
          blocked={props.trackingReady && !props.canExport}
          disabled={!props.trackingReady || props.exporting}
          onClick={props.onExport}
        >
          <Download size={17} />
        </ToolButton>
        <ToolButton title="停止任务" disabled={!props.exporting} onClick={props.onCancel}>
          <Square size={17} />
        </ToolButton>
      </div>
    </div>
  );
}
