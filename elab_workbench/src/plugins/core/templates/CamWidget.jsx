/* eslint-disable react-refresh/only-export-components */
import React, { useEffect, useState } from "react";
import { ColorPicker, Icons } from "../../../utils/Shared";
import { useTask } from "../../../hooks/useTask";
import SliderControl from "../../../components/SliderControl";

const RESOLUTIONS = [
  { value: "320x240", label: "320 x 240" },
  { value: "640x480", label: "640 x 480" },
  { value: "1280x720", label: "1280 x 720" },
  { value: "1920x1080", label: "1920 x 1080" },
];

const CamWidget = ({ task, streamBuffers }) => {
  const [frame, setFrame] = useState(null);

  useEffect(() => {
    let animationFrameId;
    const updateFrame = () => {
      const taskId = task.originalId || task.id;
      const latestFrame = streamBuffers?.get(taskId)?.getLatest?.();
      if (typeof latestFrame === "string" && latestFrame.startsWith("data:image/")) {
        setFrame(latestFrame);
      }
      animationFrameId = requestAnimationFrame(updateFrame);
    };
    animationFrameId = requestAnimationFrame(updateFrame);
    return () => cancelAnimationFrame(animationFrameId);
  }, [streamBuffers, task]);

  return (
    <div className="h-full min-h-0 flex flex-col bg-slate-950">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-800 text-xs text-slate-300">
        <Icons.Video size={15} className="text-cyan-400" />
        <span className="font-bold uppercase tracking-widest truncate">{task.name}</span>
      </div>
      <div className="relative flex-1 min-h-0 flex items-center justify-center overflow-hidden">
        {frame ? (
          <img src={frame} alt="Live camera stream" className="w-full h-full object-contain" />
        ) : (
          <div className="flex flex-col items-center gap-2 text-slate-600">
            <Icons.Camera size={30} />
            <span className="text-xs uppercase tracking-widest">Waiting for camera</span>
          </div>
        )}
      </div>
    </div>
  );
};

const CameraConfigWidget = ({ task, onUpdateTask }) => {
  const { updateConfig } = useTask(task, onUpdateTask);

  return (
    <div className="h-full overflow-y-auto custom-scrollbar p-4 space-y-5 bg-slate-900">
      <ColorPicker task={task} onUpdateTask={onUpdateTask} />
      <SliderControl
        label="Frame rate"
        value={task.config?.frameRate ?? 8}
        min="1"
        max="12"
        step="1"
        onChange={(event) => updateConfig("frameRate", Number(event.target.value))}
        unit="FPS"
        colorClass="accent-cyan-500"
        textColorClass="text-cyan-400"
      />
      <div>
        <label className="block mb-2 text-xs text-slate-400">Image size</label>
        <select
          value={task.config?.resolution || "640x480"}
          onChange={(event) => updateConfig("resolution", event.target.value)}
          className="w-full bg-slate-950 text-slate-200 text-xs p-2 border border-slate-700 rounded focus:border-cyan-500 outline-none"
        >
          {RESOLUTIONS.map((resolution) => (
            <option key={resolution.value} value={resolution.value}>{resolution.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
};

export const CamWidgetTemplate = {
  id: "system_cam_widget",
  name: "Camera Widget",
  type: "UI_TEMPLATE",
  render: CamWidget,
};

export const CameraConfigWidgetTemplate = {
  id: "tpl_camera_config",
  name: "Camera Configuration",
  type: "UI_TEMPLATE",
  render: CameraConfigWidget,
};