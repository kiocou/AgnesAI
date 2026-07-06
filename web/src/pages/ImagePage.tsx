import { useEffect, useMemo, useState } from "react";
import { Download, ImageIcon, Loader2, Maximize2, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PreviewDialog } from "@/components/studio/PreviewDialog";
import { EmptyState, Field, SectionHeader } from "@/components/studio/StudioPrimitives";
import { type ReferenceImage, UploadDropzone } from "@/components/studio/UploadDropzone";
import { useToast } from "@/components/studio/ToastProvider";
import { apiJson, type ImageItem } from "@/lib/api";
import { downloadSource, mediaSource, truncate } from "@/lib/utils";

const imageModelSizes: Record<string, { value: string; label: string }[]> = {
  "agnes-image-2.0-flash": [
    { value: "512x512", label: "512 x 512 方形" },
    { value: "768x768", label: "768 x 768 方形" },
    { value: "1024x1024", label: "1024 x 1024 方形" },
    { value: "768x1152", label: "768 x 1152 竖版" },
    { value: "1024x1536", label: "1024 x 1536 竖版" },
  ],
  "agnes-image-2.1-flash": [
    { value: "512x512", label: "512 x 512 方形" },
    { value: "1024x768", label: "1024 x 768 横版" },
    { value: "1152x768", label: "1152 x 768 横版" },
    { value: "1024x1024", label: "1024 x 1024 方形" },
    { value: "1024x1536", label: "1024 x 1536 竖版" },
    { value: "2048x1152", label: "2048 x 1152 2K 横版" },
    { value: "2048x2048", label: "2048 x 2048 2K 方形" },
  ],
};

function mergeImages(nextImages: ImageItem[], currentImages: ImageItem[]) {
  const seen = new Set<string>();
  return [...nextImages, ...currentImages].filter((item) => {
    const key = item.local_path || item.url || `${item.prompt || ""}-${item.created_at || ""}`;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function ImagePage() {
  const toast = useToast();
  const [prompt, setPrompt] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [model, setModel] = useState("agnes-image-2.1-flash");
  const [size, setSize] = useState("1152x768");
  const [count, setCount] = useState("1");
  const [seed, setSeed] = useState("");
  const [references, setReferences] = useState<ReferenceImage[]>([]);
  const [images, setImages] = useState<ImageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<{ src: string; item?: ImageItem } | null>(null);

  const sizes = useMemo(() => imageModelSizes[model] || imageModelSizes["agnes-image-2.1-flash"], [model]);

  useEffect(() => {
    if (!sizes.some((item) => item.value === size)) {
      setSize(sizes[0]?.value || "1024x1024");
    }
  }, [size, sizes]);

  useEffect(() => {
    void loadImageHistory();
  }, []);

  async function loadImageHistory() {
    try {
      const data = await apiJson<{ images: ImageItem[] }>("/api/image/history");
      setImages(data.images || []);
    } catch (error) {
      console.warn(error);
    }
  }

  async function generateImages() {
    if (!prompt.trim()) {
      toast("请输入图片 Prompt", "error");
      return;
    }
    setLoading(true);
    try {
      const data = await apiJson<{ images: ImageItem[] }>("/api/image/generate", {
        method: "POST",
        body: JSON.stringify({
          prompt: prompt.trim(),
          negative_prompt: negativePrompt.trim(),
          model,
          size,
          count: Number(count),
          seed: seed.trim(),
          input_images: references.map((item) => item.value).filter(Boolean),
        }),
      });
      setImages((current) => mergeImages(data.images || [], current));
      toast(`成功生成 ${data.images?.length || 0} 张图片`);
    } catch (error) {
      toast(error instanceof Error ? error.message : "图片生成失败", "error");
    } finally {
      setLoading(false);
    }
  }

  async function addDownload(item: ImageItem, name = "agnes_image.png") {
    const url = downloadSource(item);
    if (!url) {
      toast("没有可下载的图片链接", "error");
      return;
    }
    try {
      await apiJson("/api/download", {
        method: "POST",
        body: JSON.stringify({ url, file_name: name }),
      });
      toast("已加入下载队列");
    } catch (error) {
      toast(error instanceof Error ? error.message : "加入下载失败", "error");
    }
  }

  return (
    <div className="grid min-h-full min-w-0 gap-5 pb-6 xl:grid-cols-[390px_minmax(0,1fr)] xl:items-start">
      <section className="panel motion-panel min-w-0 p-5">
        <SectionHeader eyebrow="Image Lab" title="图片生成" description="用提示词、负面词和参考图控制风格，结果会自动进入历史记录。" />
        <div className="space-y-4">
          <Field label="Prompt">
            <Textarea
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="描述画面主体、构图、镜头、光线和风格..."
              className="min-h-[132px]"
            />
          </Field>
          <Field label="Negative Prompt">
            <Textarea
              value={negativePrompt}
              onChange={(event) => setNegativePrompt(event.target.value)}
              placeholder="不希望出现的元素，例如 blurry, watermark..."
              className="min-h-[72px]"
            />
          </Field>
          <UploadDropzone
            title={references.length ? `已选择 ${references.length} 张参考图` : "上传参考图"}
            description="支持拖拽或点击上传，多张参考图会一起送入图生图流程。"
            images={references}
            onChange={setReferences}
            onError={(message) => toast(message, "error")}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="模型">
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="agnes-image-2.1-flash">Agnes Image 2.1 Flash</SelectItem>
                  <SelectItem value="agnes-image-2.0-flash">Agnes Image 2.0 Flash</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="尺寸">
              <Select value={size} onValueChange={setSize}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {sizes.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                      {item.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="数量">
              <Select value={count} onValueChange={setCount}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4].map((value) => (
                    <SelectItem key={value} value={String(value)}>
                      {value} 张
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Seed">
              <Input value={seed} onChange={(event) => setSeed(event.target.value)} placeholder="留空随机" />
            </Field>
          </div>
          <Button className="w-full" onClick={generateImages} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {loading ? "生成中" : "开始生成"}
          </Button>
        </div>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">作品画廊</h3>
            <p className="text-xs text-muted-foreground">最新生成结果和历史图片会在这里快速取用。</p>
          </div>
          <Button variant="outline" size="sm" onClick={loadImageHistory}>
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
              正在向 Agnes 提交图片生成任务...
            </div>
          </div>
        ) : null}

        {images.length ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
            {images.map((image, index) => {
              const src = mediaSource(image);
              if (!src) return null;
              return (
                <article
                  key={`${src}-${index}`}
                  className="panel-tight motion-card group overflow-hidden"
                  style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                >
                  <button className="media-checker block aspect-[4/3] w-full overflow-hidden" onClick={() => setPreview({ src, item: image })}>
                    <img src={src} alt={image.prompt || "Generated image"} className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                  </button>
                  <div className="flex items-center justify-between gap-3 p-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">Image {index + 1}</div>
                      <div className="truncate text-xs text-muted-foreground">{truncate(image.prompt || prompt || "Agnes image", 44)}</div>
                    </div>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" onClick={() => setPreview({ src, item: image })} title="预览">
                        <Maximize2 className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => void addDownload(image, `agnes_image_${index + 1}.png`)} title="下载">
                        <Download className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <EmptyState
            icon={<ImageIcon className="h-6 w-6" />}
            title="还没有图片"
            description="写一个 Prompt 并开始生成，结果会以可预览、可下载的卡片显示。"
          />
        )}
      </section>

      {preview ? (
        <PreviewDialog
          src={preview.src}
          type="image"
          title="图片预览"
          onOpenChange={(open) => {
            if (!open) setPreview(null);
          }}
          onDownload={preview.item ? () => void addDownload(preview.item!, "agnes_image.png") : undefined}
        />
      ) : null}
    </div>
  );
}
