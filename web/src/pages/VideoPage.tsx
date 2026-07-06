import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Film, ImageIcon, Loader2, Maximize2, Play, RectangleHorizontal, RectangleVertical, RefreshCw, Square, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PreviewDialog } from "@/components/studio/PreviewDialog";
import { EmptyState, Field, SectionHeader } from "@/components/studio/StudioPrimitives";
import { type ReferenceImage, UploadDropzone } from "@/components/studio/UploadDropzone";
import { useToast } from "@/components/studio/ToastProvider";
import { apiJson, type ImageItem, type VideoTask } from "@/lib/api";
import { fileToDataUri, formatTime, isVideoStatusActive, mediaSource, playableVideoUrl, truncate } from "@/lib/utils";

type VideoMode = "text" | "image" | "multi_image" | "keyframes";
type VideoRatio = "landscape" | "portrait" | "square";

const durationPresets = [5, 8, 10, 12, 15, 18];

const videoResolutionGroups: Record<
  VideoRatio,
  {
    label: string;
    detail: string;
    icon: typeof RectangleHorizontal;
    resolutions: { value: string; label: string; quality: string }[];
  }
> = {
  landscape: {
    label: "横屏",
    detail: "6 个规格",
    icon: RectangleHorizontal,
    resolutions: [
      { value: "1152x768", label: "1152 x 768", quality: "3:2 默认" },
      { value: "1536x1024", label: "1536 x 1024", quality: "3:2 高" },
      { value: "1280x720", label: "1280 x 720", quality: "16:9 720p" },
      { value: "1920x1088", label: "1920 x 1088", quality: "16:9 1080p" },
      { value: "1024x768", label: "1024 x 768", quality: "4:3 标准" },
      { value: "1408x1056", label: "1408 x 1056", quality: "4:3 高" },
    ],
  },
  portrait: {
    label: "竖屏",
    detail: "6 个规格",
    icon: RectangleVertical,
    resolutions: [
      { value: "768x1152", label: "768 x 1152", quality: "2:3 默认" },
      { value: "1024x1536", label: "1024 x 1536", quality: "2:3 高" },
      { value: "720x1280", label: "720 x 1280", quality: "9:16 720p" },
      { value: "1088x1920", label: "1088 x 1920", quality: "9:16 1080p" },
      { value: "768x1024", label: "768 x 1024", quality: "3:4 标准" },
      { value: "1056x1408", label: "1056 x 1408", quality: "3:4 高" },
    ],
  },
  square: {
    label: "方形",
    detail: "3 个规格",
    icon: Square,
    resolutions: [
      { value: "512x512", label: "512 x 512", quality: "轻量" },
      { value: "768x768", label: "768 x 768", quality: "标准" },
      { value: "1024x1024", label: "1024 x 1024", quality: "高" },
    ],
  },
};

const videoRatioOrder: VideoRatio[] = ["landscape", "portrait", "square"];

function statusBadge(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "completed" || normalized === "success") return { label: "已完成", variant: "success" as const };
  if (normalized === "failed" || normalized === "error") return { label: "失败", variant: "destructive" as const };
  if (isVideoStatusActive(status)) return { label: "生成中", variant: "warning" as const };
  return { label: status || "未知", variant: "muted" as const };
}

export function VideoPage() {
  const toast = useToast();
  const [mode, setMode] = useState<VideoMode>("text");
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [ratio, setRatio] = useState<VideoRatio>("landscape");
  const [resolution, setResolution] = useState("1152x768");
  const [fps, setFps] = useState("24");
  const [duration, setDuration] = useState("5");
  const [references, setReferences] = useState<ReferenceImage[]>([]);
  const [tasks, setTasks] = useState<VideoTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerImages, setPickerImages] = useState<ImageItem[]>([]);
  const [preview, setPreview] = useState<{ src: string; task?: VideoTask } | null>(null);

  const needsImage = mode !== "text";
  const activeTasks = useMemo(() => tasks.filter((task) => isVideoStatusActive(task.status)), [tasks]);
  const queueTasks = useMemo(
    () =>
      tasks.filter((task) => {
        const normalized = String(task.status || "").toLowerCase();
        return isVideoStatusActive(normalized) || (["failed", "error"].includes(normalized) && !task.result_url && !task.local_path);
      }),
    [tasks],
  );
  const galleryTasks = useMemo(
    () => tasks.filter((task) => !isVideoStatusActive(task.status) && (task.status === "completed" || task.result_url || task.local_path)),
    [tasks],
  );
  const activeCount = activeTasks.length;
  const resolutionOptions = videoResolutionGroups[ratio].resolutions;
  const durationSeconds = Math.max(5, Math.min(18, Number(duration) || 5));
  const durationFrames = durationSeconds * Number(fps || 24) + 1;

  const loadTasks = useCallback(async (poll = false) => {
    const endpoint = poll ? "/api/video/poll-all" : "/api/video/tasks";
    const data = await apiJson<{ tasks: VideoTask[] }>(endpoint);
    setTasks(data.tasks || []);
  }, []);

  useEffect(() => {
    void loadTasks().catch(console.warn);
  }, [loadTasks]);

  useEffect(() => {
    if (!activeCount) return undefined;
    const timer = window.setInterval(() => {
      void loadTasks(true).catch(console.warn);
    }, activeCount ? 3000 : 5000);
    return () => window.clearInterval(timer);
  }, [activeCount, loadTasks]);

  useEffect(() => {
    if (!needsImage && references.length) setReferences([]);
  }, [needsImage, references.length]);

  useEffect(() => {
    if (!resolutionOptions.some((item) => item.value === resolution)) {
      setResolution(resolutionOptions[0]?.value || "1152x768");
    }
  }, [resolution, resolutionOptions]);

  function chooseRatio(nextRatio: VideoRatio) {
    setRatio(nextRatio);
    setResolution(videoResolutionGroups[nextRatio].resolutions[0]?.value || "1152x768");
  }

  function taskVideoSource(task: VideoTask) {
    return task.local_path ? `/api/file?path=${encodeURIComponent(task.local_path)}` : playableVideoUrl(task.task_id, task.result_url);
  }

  async function createVideo() {
    if (!prompt.trim()) {
      toast("请输入视频 Prompt", "error");
      return;
    }
    if (needsImage && !references.length) {
      toast("请先上传或选择参考图片", "error");
      return;
    }
    setLoading(true);
    try {
      const task = await apiJson<VideoTask>("/api/video/create", {
        method: "POST",
        body: JSON.stringify({
          prompt: prompt.trim(),
          negative_prompt: negativePrompt.trim(),
          model: "agnes-video-v2.0",
          mode,
          resolution,
          fps: Number(fps),
          duration_seconds: Number(duration),
          image_base64: references[0]?.value || "",
          image_inputs: references.map((item) => item.value).filter(Boolean),
        }),
      });
      setTasks((current) => [task, ...current.filter((item) => item.task_id !== task.task_id)]);
      toast("视频任务已创建");
      void loadTasks(true);
    } catch (error) {
      toast(error instanceof Error ? error.message : "视频任务创建失败", "error");
    } finally {
      setLoading(false);
    }
  }

  async function cancelTask(taskId: string) {
    try {
      await apiJson(`/api/video/cancel/${taskId}`, { method: "POST" });
      toast("任务已取消");
      void loadTasks();
    } catch (error) {
      toast(error instanceof Error ? error.message : "取消失败", "error");
    }
  }

  async function addDownload(task: VideoTask) {
    const url = task.result_url || (task.local_path ? `${window.location.origin}/api/file?path=${encodeURIComponent(task.local_path)}` : "");
    if (!url) {
      toast("没有可下载的视频链接", "error");
      return;
    }
    try {
      await apiJson("/api/download", {
        method: "POST",
        body: JSON.stringify({ url, file_name: "agnes_video.mp4" }),
      });
      toast("已加入下载队列");
    } catch (error) {
      toast(error instanceof Error ? error.message : "加入下载失败", "error");
    }
  }

  async function openImagePicker() {
    setPickerOpen(true);
    try {
      const data = await apiJson<{ images: ImageItem[] }>("/api/image/history");
      setPickerImages(data.images || []);
    } catch (error) {
      toast(error instanceof Error ? error.message : "读取图片历史失败", "error");
    }
  }

  async function selectHistoryImage(image: ImageItem) {
    const src = mediaSource(image);
    if (!src) return;
    try {
      let value = image.url || "";
      if (!value) {
        const blob = await fetch(src).then((response) => response.blob());
        value = await fileToDataUri(new File([blob], "history-image.png", { type: blob.type || "image/png" }));
      }
      const nextImage = { value, src, label: truncate(image.prompt || "历史图片", 28) };
      setReferences((current) => (mode === "image" ? [nextImage] : [...current, nextImage]));
      setPickerOpen(false);
      toast("已添加历史图片");
    } catch (error) {
      toast(error instanceof Error ? error.message : "选择图片失败", "error");
    }
  }

  return (
    <div className="grid min-h-full min-w-0 gap-5 pb-6 xl:grid-cols-[390px_minmax(0,1fr)] xl:items-start">
      <section className="panel motion-panel min-w-0 p-5">
        <SectionHeader eyebrow="Motion Desk" title="视频生成" description="创建文生视频、图生视频、多图视频任务，并实时追踪生成进度。" />
        <div className="space-y-4">
          <Field label="模式">
            <Select value={mode} onValueChange={(value) => setMode(value as VideoMode)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text">文生视频</SelectItem>
                <SelectItem value="image">图生视频</SelectItem>
                <SelectItem value="multi_image">多图视频</SelectItem>
                <SelectItem value="keyframes">关键帧动画</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Prompt">
            <Textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="描述主体动作、镜头运动、场景变化和氛围..."
              className="min-h-[132px]"
            />
          </Field>
          <Field label="Negative Prompt">
            <Textarea
              value={negativePrompt}
              onChange={(event) => setNegativePrompt(event.target.value)}
              placeholder="不希望出现的抖动、变形、水印等..."
              className="min-h-[72px]"
            />
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="画面比例与分辨率" className="sm:col-span-3">
              <div className="space-y-3 rounded-lg border bg-background p-3">
                <div className="grid grid-cols-3 gap-2">
                  {videoRatioOrder.map((item) => {
                    const group = videoResolutionGroups[item];
                    const Icon = group.icon;
                    const active = ratio === item;
                    return (
                      <button
                        key={item}
                        type="button"
                        className={[
                          "flex h-14 min-w-0 items-center gap-2 rounded-md border px-3 text-left transition",
                          active
                            ? "border-primary bg-primary/10 text-primary shadow-sm"
                            : "border-input bg-muted/20 text-foreground hover:border-primary/45 hover:bg-muted/45",
                        ].join(" ")}
                        onClick={() => chooseRatio(item)}
                        aria-pressed={active}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="min-w-0">
                          <span className="block whitespace-nowrap text-xs font-semibold">{group.label}</span>
                          <span className="block truncate text-[11px] text-muted-foreground">{group.detail}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
                <Select value={resolution} onValueChange={setResolution}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {resolutionOptions.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label} · {item.quality}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </Field>
            <Field label="帧率">
              <Select value={fps} onValueChange={setFps}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="24">24 FPS</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="时长" className="sm:col-span-3">
              <div className="rounded-lg border bg-background p-3">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="text-2xl font-bold leading-none text-primary">{durationSeconds}s</div>
                  <div className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">{durationFrames} 帧</div>
                </div>
                <input
                  aria-label="视频时长"
                  className="duration-range"
                  type="range"
                  min={5}
                  max={18}
                  step={1}
                  value={durationSeconds}
                  onChange={(event) => setDuration(event.target.value)}
                />
                <div className="mt-3 grid grid-cols-6 gap-1">
                  {durationPresets.map((seconds) => (
                    <button
                      key={seconds}
                      type="button"
                      className={[
                        "h-7 rounded-md border text-xs font-semibold transition",
                        durationSeconds === seconds ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:border-primary/60 hover:bg-muted",
                      ].join(" ")}
                      onClick={() => setDuration(String(seconds))}
                    >
                      {seconds}s
                    </button>
                  ))}
                </div>
              </div>
            </Field>
          </div>

          {needsImage ? (
            <UploadDropzone
              title={references.length ? `已选择 ${references.length} 张参考图` : "上传视频参考图"}
              description={mode === "image" ? "图生视频使用第一张参考图。" : "多图或关键帧模式可加入多张参考图。"}
              images={references}
              multiple={mode !== "image"}
              onChange={setReferences}
              onError={(message) => toast(message, "error")}
              actions={
                <Button type="button" variant="outline" size="sm" className="w-full" onClick={openImagePicker}>
                  <ImageIcon className="h-4 w-4" />
                  从生成历史选择
                </Button>
              }
            />
          ) : null}

          <Button className="w-full" onClick={createVideo} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Video className="h-4 w-4" />}
            {loading ? "创建中" : "开始生成视频"}
          </Button>
        </div>
      </section>

      <section className="min-w-0 space-y-6">
        <div>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">生成进度</h3>
              <p className="text-xs text-muted-foreground">{activeCount ? `${activeCount} 个任务正在生成` : "当前没有活跃视频任务"}</p>
            </div>
            <Button variant="outline" size="sm" onClick={() => void loadTasks(true)}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
          </div>

          {loading ? (
            <div className="panel-tight motion-panel relative mb-4 overflow-hidden p-5">
              <div className="absolute inset-x-0 top-0 h-1 bg-primary/20">
                <div className="h-full w-1/3 animate-scanline bg-primary" />
              </div>
              <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
                正在创建视频任务...
              </div>
            </div>
          ) : null}

          {queueTasks.length ? (
            <div className="space-y-3">
              {queueTasks.map((task, index) => {
              const badge = statusBadge(task.status);
              const isActive = isVideoStatusActive(task.status);
              const isCompleted = badge.label === "已完成";
              const actualProgress = Math.max(0, Math.min(100, Number(task.progress || 0)));
              const visibleProgress = isCompleted ? 100 : actualProgress || (isActive ? 4 : 0);
              const progressText = isActive && actualProgress === 0 ? "排队中" : `${isCompleted ? 100 : actualProgress}%`;
              const videoSrc = taskVideoSource(task);
              return (
                <article key={task.task_id} className="panel-tight motion-card p-4" style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}>
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
                    <button
                      className="media-checker flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border lg:w-48"
                      onClick={() => videoSrc && setPreview({ src: videoSrc, task })}
                      disabled={!videoSrc}
                    >
                      {videoSrc ? (
                        <video src={videoSrc} preload="metadata" muted className="h-full w-full bg-black object-cover" />
                      ) : (
                        <Film className="h-8 w-8 text-muted-foreground" />
                      )}
                    </button>
                    <div className="min-w-0 flex-1 space-y-3">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate text-sm font-semibold">{truncate(task.prompt, 92)}</div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {task.mode || "text"} / {task.resolution || resolution} / {task.duration_seconds || duration}s / {formatTime(task.created_at)}
                          </div>
                        </div>
                        <Badge variant={badge.variant}>{badge.label}</Badge>
                      </div>
                      <div className="space-y-1">
                        <Progress value={visibleProgress} />
                        <div className="flex justify-between text-xs text-muted-foreground">
                          <span>{task.task_id.slice(0, 12)}</span>
                          <span>{progressText}</span>
                        </div>
                      </div>
                      {task.error ? <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">{task.error}</div> : null}
                    </div>
                    <div className="flex gap-2 lg:flex-col">
                      <Button variant="outline" size="sm" disabled={!videoSrc} onClick={() => videoSrc && setPreview({ src: videoSrc, task })}>
                        <Play className="h-4 w-4" />
                        预览
                      </Button>
                      <Button variant="outline" size="sm" disabled={!task.result_url && !task.local_path} onClick={() => void addDownload(task)}>
                        <Download className="h-4 w-4" />
                        下载
                      </Button>
                      {isActive ? (
                        <Button variant="ghost" size="sm" className="text-destructive" onClick={() => void cancelTask(task.task_id)}>
                          <Square className="h-4 w-4" />
                          取消
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </article>
              );
              })}
            </div>
          ) : null}
        </div>

        <div>
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">作品画廊</h3>
              <p className="text-xs text-muted-foreground">完成的视频会在这里按最新顺序展示。</p>
            </div>
            <Badge variant="secondary">视频 {galleryTasks.length}</Badge>
          </div>

          {galleryTasks.length ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
              {galleryTasks.map((task, index) => {
                const videoSrc = taskVideoSource(task);
                return (
                  <article
                    key={`${task.task_id}-gallery`}
                    className="panel-tight motion-card group overflow-hidden"
                    style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                  >
                    <button className="media-checker flex aspect-video w-full items-center justify-center overflow-hidden" onClick={() => videoSrc && setPreview({ src: videoSrc, task })} disabled={!videoSrc}>
                      {videoSrc ? (
                        <video src={videoSrc} preload="metadata" muted className="h-full w-full bg-black object-cover transition duration-300 group-hover:scale-[1.03]" />
                      ) : (
                        <Film className="h-8 w-8 text-muted-foreground" />
                      )}
                    </button>
                    <div className="space-y-3 p-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">Video {index + 1}</div>
                        <div className="truncate text-xs text-muted-foreground">{truncate(task.prompt || "Agnes video", 52)}</div>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0 text-xs text-muted-foreground">
                          {task.resolution || resolution} / {task.duration_seconds || duration}s
                        </div>
                        <div className="flex gap-1">
                          <Button variant="ghost" size="icon" disabled={!videoSrc} onClick={() => videoSrc && setPreview({ src: videoSrc, task })} title="预览">
                            <Maximize2 className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" disabled={!task.result_url && !task.local_path} onClick={() => void addDownload(task)} title="下载">
                            <Download className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState icon={<Film className="h-6 w-6" />} title="还没有视频作品" description="生成完成的视频会以可预览、可下载的卡片显示。" />
          )}
        </div>
      </section>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>选择历史图片</DialogTitle>
          </DialogHeader>
          {pickerImages.length ? (
            <div className="grid max-h-[62vh] grid-cols-2 gap-3 overflow-y-auto pr-1 md:grid-cols-4">
              {pickerImages.map((image, index) => {
                const src = mediaSource(image);
                return (
                  <button
                    key={`${src}-${index}`}
                    className="motion-card group overflow-hidden rounded-lg border bg-muted text-left transition hover:border-primary"
                    style={{ animationDelay: `${Math.min(index, 12) * 28}ms` }}
                    onClick={() => void selectHistoryImage(image)}
                  >
                    <img src={src} alt={image.prompt || "history image"} className="aspect-square w-full object-cover transition group-hover:scale-[1.03]" />
                    <div className="p-2 text-xs text-muted-foreground">{truncate(image.prompt || "历史图片", 32)}</div>
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyState title="暂无历史图片" description="先在图片生成页生成图片，再回到这里选择。" />
          )}
        </DialogContent>
      </Dialog>

      {preview ? (
        <PreviewDialog
          src={preview.src}
          type="video"
          title="视频预览"
          onOpenChange={(open) => {
            if (!open) setPreview(null);
          }}
          onDownload={preview.task ? () => void addDownload(preview.task!) : undefined}
        />
      ) : null}
    </div>
  );
}
