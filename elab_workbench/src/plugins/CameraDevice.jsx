import PluginBuilder from "./core/PluginBuilder";

const DEFAULT_FRAME_RATE = 8;
const DEFAULT_WIDTH = 640;
const DEFAULT_HEIGHT = 480;
const JPEG_QUALITY = 0.7;

export const CameraClientPlugin = new PluginBuilder("system_camera_v1", "Browser Camera", "SENSOR")
  .setCapabilities(["capture", "stream"])
  .setDescription("Streams webcam JPEG frames through the dispatcher")
  .setSimulation({
    alwaysRun: true,
    factory: (initialTask, dispatcher) => {
      let stream;
      let intervalId;
      let emitFrame;
      let currentConfig = { ...initialTask.config };
      const sourceId = initialTask.originalId || initialTask.id;

      const clampFrameRate = (value) =>
        Math.min(12, Math.max(1, Number(value) || DEFAULT_FRAME_RATE));

      // Restart only the emit loop so an FPS change never tears down the
      // camera stream (which would cause a visible black flicker).
      const restartEmitLoop = () => {
        if (intervalId) clearInterval(intervalId);
        intervalId = undefined;
        if (!emitFrame) return;
        const frameRate = clampFrameRate(currentConfig.frameRate);
        intervalId = setInterval(emitFrame, 1000 / frameRate);
      };

      const stopCapture = () => {
        if (intervalId) clearInterval(intervalId);
        intervalId = undefined;
        emitFrame = undefined;
        stream?.getTracks().forEach((track) => track.stop());
        stream = undefined;
      };

      const startCapture = async () => {
        if (!navigator.mediaDevices?.getUserMedia) {
          console.error("Camera access requires a secure browser context.");
          return;
        }

        try {
          const [width, height] = String(currentConfig.resolution || `${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}`)
            .split("x")
            .map(Number);
          stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: width }, height: { ideal: height } },
            audio: false,
          });
          const video = document.createElement("video");
          const canvas = document.createElement("canvas");
          const context = canvas.getContext("2d", { alpha: false });
          video.srcObject = stream;
          video.muted = true;
          video.playsInline = true;
          await video.play();

          canvas.width = video.videoWidth || width;
          canvas.height = video.videoHeight || height;
          emitFrame = () => {
            if (!context || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            const image = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
            if (dispatcher.socket?.connected) {
              dispatcher.socket.emit("data_stream", {
                sourceId,
                image_b64: image,
                timestamp: Date.now(),
              });
            }
          };

          restartEmitLoop();
        } catch (error) {
          console.error("Unable to start camera capture:", error);
          stopCapture();
        }
      };

      const controlHandler = (data) => {
        if (data.provider_id === `prov_${initialTask.originalId || initialTask.id}` && data.command?.action === "update_config") {
          const nextConfig = { ...currentConfig, ...data.command.payload };
          const resolutionChanged = nextConfig.resolution !== currentConfig.resolution;
          currentConfig = nextConfig;
          if (resolutionChanged || !stream) {
            // Resolution changes require a new media stream.
            stopCapture();
            void startCapture();
          } else {
            // FPS-only change: just retime the emit loop, keep the stream live.
            restartEmitLoop();
          }
        }
      };

      dispatcher.socket?.on("execute_command", controlHandler);
      void startCapture();

      return () => {
        dispatcher.socket?.off("execute_command", controlHandler);
        stopCapture();
      };
    },
  })
  .setCreateTask(() => ({
    id: `camera_${Date.now()}`,
    groupId: "system_camera_v1",
    type: "SENSOR",
    name: "Browser Camera",
    color: "#06b6d4",
    virtual: true,
    tags: ["Camera", "Video", "Sensor"],
    config: {
      frameRate: DEFAULT_FRAME_RATE,
      resolution: `${DEFAULT_WIDTH}x${DEFAULT_HEIGHT}`,
    },
    ui: {
      mode: "generic",
      defaultTemplate: "system_cam_widget",
      views: [
        { id: "camera", label: "Camera", icon: "Camera", template: "system_cam_widget" },
        { id: "config", label: "Config", icon: "Settings", template: "tpl_camera_config" },
      ],
    },
  }))
  .build();