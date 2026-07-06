import { useEffect, useMemo, useState } from "react";
import { Download, History, ImageIcon, RefreshCw, Search, Trash2, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PreviewDialog } from "@/components/studio/PreviewDialog";
import { EmptyState, SectionHeader } from "@/components/studio/StudioPrimitives";
import { useToast } from "@/components/studio/ToastProvider";
import { apiJson, imageItemsFromRecord, type HistoryRecord, type ImageItem } from "@/lib/api";
import { downloadSource, formatTime, mediaSource, playableVideoUrl, truncate } from "@/lib/utils";

type PreviewState = {
  src: string;
  type: "image" | "video";
  item?: ImageItem;
  record?: HistoryRecord;
};

function recordPreview(record: HistoryRecord) {
  if (record.kind === "image") {
    const first = imageItemsFromRecord(record)[0];
    return first ? mediaSource(first) : "";
  }
  if (record.local_path) return `/api/file?path=${encodeURIComponent(record.local_path)}`;
  return playableVideoUrl(record.task_id, record.result_url);
}

export function HistoryPage() {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);

  const counts = useMemo(
    () => ({
      image: records.filter((record) => record.kind === "image").length,
      video: records.filter((record) => record.kind === "video").length,
    }),
    [records],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadHistory();
    }, 180);
    return () => window.clearTimeout(timer);
  }, [query]);

  async function loadHistory() {
    setLoading(true);
    try {
      const data = await apiJson<{ records: HistoryRecord[] }>(`/api/history?q=${encodeURIComponent(query)}`);
      setRecords(data.records || []);
    } catch (error) {
      toast(error instanceof Error ? error.message : "读取历史失败", "error");
    } finally {
      setLoading(false);
    }
  }

  async function deleteRecord(record: HistoryRecord) {
    try {
      await apiJson(`/api/history/${record.kind}/${record.id}`, { method: "DELETE" });
      setRecords((current) => current.filter((item) => !(item.kind === record.kind && item.id === record.id)));
      toast("历史记录已删除");
    } catch (error) {
      toast(error instanceof Error ? error.message : "删除失败", "error");
    }
  }

  async function clearHistory() {
    if (!window.confirm("确定清空所有历史记录吗？")) return;
    try {
      await apiJson("/api/history", { method: "DELETE" });
      setRecords([]);
      toast("历史记录已清空");
    } catch (error) {
      toast(error instanceof Error ? error.message : "清空失败", "error");
    }
  }

  async function addImageDownload(item: ImageItem, index = 0) {
    const url = downloadSource(item);
    if (!url) {
      toast("没有可下载链接", "error");
      return;
    }
    await apiJson("/api/download", {
      method: "POST",
      body: JSON.stringify({ url, file_name: `history_image_${index + 1}.png` }),
    });
  }

  async function addDownloads(record: HistoryRecord) {
    try {
      if (record.kind === "image") {
        const items = imageItemsFromRecord(record);
        if (!items.length) throw new Error("没有可下载图片");
        await Promise.all(items.map((item, index) => addImageDownload(item, index)));
        toast(`已加入 ${items.length} 张图片到下载队列`);
      } else {
        const url = record.result_url || (record.local_path ? `${window.location.origin}/api/file?path=${encodeURIComponent(record.local_path)}` : "");
        if (!url) throw new Error("没有可下载视频");
        await apiJson("/api/download", {
          method: "POST",
          body: JSON.stringify({ url, file_name: "history_video.mp4" }),
        });
        toast("已加入下载队列");
      }
    } catch (error) {
      toast(error instanceof Error ? error.message : "加入下载失败", "error");
    }
  }

  function openRecord(record: HistoryRecord) {
    if (record.kind === "image") {
      const item = imageItemsFromRecord(record)[0];
      const src = item ? mediaSource(item) : "";
      if (src) setPreview({ src, type: "image", item, record });
      return;
    }
    const src = recordPreview(record);
    if (src) setPreview({ src, type: "video", record });
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <SectionHeader
        eyebrow="Archive"
        title="历史记录"
        description="集中查看图片和视频生成记录，可快速预览、下载或删除。"
        action={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void loadHistory()}>
              <RefreshCw className="h-4 w-4" />
              刷新
            </Button>
            <Button variant="destructive" size="sm" onClick={() => void clearHistory()}>
              <Trash2 className="h-4 w-4" />
              清空
            </Button>
          </div>
        }
      />

      <div className="panel-tight motion-panel mb-4 flex flex-col gap-3 p-3 md:flex-row md:items-center md:justify-between">
        <div className="relative md:w-[420px]">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} className="pl-9" placeholder="搜索 Prompt / 模型 / 任务 ID" />
        </div>
        <div className="flex gap-2 text-xs">
          <Badge variant="secondary">图片 {counts.image}</Badge>
          <Badge variant="secondary">视频 {counts.video}</Badge>
          {loading ? <Badge variant="warning">读取中</Badge> : null}
        </div>
      </div>

      {records.length ? (
        <div className="space-y-3">
          {records.map((record, index) => {
            const src = recordPreview(record);
            const kindLabel = record.kind === "image" ? "图片" : "视频";
            return (
              <article
                key={`${record.kind}-${record.id}`}
                className="panel-tight motion-card p-3"
                style={{ animationDelay: `${Math.min(index, 10) * 36}ms` }}
              >
                <div className="grid gap-3 lg:grid-cols-[112px_minmax(0,1fr)_auto] lg:items-center">
                  <button
                    className="media-checker flex aspect-video w-full items-center justify-center overflow-hidden rounded-md border lg:aspect-square"
                    onClick={() => openRecord(record)}
                  >
                    {src ? (
                      record.kind === "image" ? (
                        <img src={src} alt={record.prompt} className="h-full w-full object-cover" />
                      ) : (
                        <video src={src} preload="metadata" muted className="h-full w-full bg-black object-cover" />
                      )
                    ) : record.kind === "image" ? (
                      <ImageIcon className="h-7 w-7 text-muted-foreground" />
                    ) : (
                      <Video className="h-7 w-7 text-muted-foreground" />
                    )}
                  </button>
                  <div className="min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <Badge variant={record.kind === "video" ? "default" : "outline"}>{kindLabel}</Badge>
                      {record.status ? <Badge variant={record.status === "completed" ? "success" : "muted"}>{record.status}</Badge> : null}
                      <span className="text-xs text-muted-foreground">{formatTime(record.created_at)}</span>
                    </div>
                    <div className="truncate text-sm font-semibold">{truncate(record.prompt, 120)}</div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                      <span>{record.model}</span>
                      {record.meta ? <span>{record.meta}</span> : null}
                      {record.task_id ? <span>Task {record.task_id.slice(0, 12)}</span> : null}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 lg:justify-end">
                    <Button variant="outline" size="sm" disabled={!src} onClick={() => openRecord(record)}>
                      预览
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => void addDownloads(record)}>
                      <Download className="h-4 w-4" />
                      下载
                    </Button>
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => void deleteRecord(record)}>
                      <Trash2 className="h-4 w-4" />
                      删除
                    </Button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState icon={<History className="h-6 w-6" />} title="暂无历史记录" description="生成图片或视频后，完整参数和结果会自动保存到这里。" />
      )}

      {preview ? (
        <PreviewDialog
          src={preview.src}
          type={preview.type}
          title={preview.type === "image" ? "图片预览" : "视频预览"}
          onOpenChange={(open) => {
            if (!open) setPreview(null);
          }}
          onDownload={preview.record ? () => void addDownloads(preview.record!) : undefined}
        />
      ) : null}
    </div>
  );
}
