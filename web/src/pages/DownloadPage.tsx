import { useCallback, useEffect, useState } from "react";
import { DownloadCloud, FileDown, RefreshCw, RotateCcw, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { PreviewDialog } from "@/components/studio/PreviewDialog";
import { EmptyState, SectionHeader } from "@/components/studio/StudioPrimitives";
import { useToast } from "@/components/studio/ToastProvider";
import { apiJson, type DownloadItem } from "@/lib/api";
import { formatTime, truncate } from "@/lib/utils";

function downloadBadge(status: string) {
  if (status === "completed") return { label: "已完成", variant: "success" as const };
  if (status === "failed") return { label: "失败", variant: "destructive" as const };
  if (status === "downloading" || status === "queued") return { label: status === "queued" ? "等待中" : "下载中", variant: "warning" as const };
  return { label: status || "未知", variant: "muted" as const };
}

export function DownloadPage({ active = true }: { active?: boolean }) {
  const toast = useToast();
  const [downloads, setDownloads] = useState<DownloadItem[]>([]);
  const [preview, setPreview] = useState<{ src: string; type: "image" | "video" } | null>(null);

  const loadDownloads = useCallback(async () => {
    const data = await apiJson<{ downloads: DownloadItem[] }>("/api/downloads");
    setDownloads(data.downloads || []);
  }, []);

  useEffect(() => {
    void loadDownloads().catch(console.warn);
  }, [loadDownloads]);

  useEffect(() => {
    if (!active) return undefined;
    void loadDownloads().catch(console.warn);
    const timer = window.setInterval(() => {
      void loadDownloads().catch(console.warn);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [active, loadDownloads]);

  async function deleteDownload(id: number) {
    try {
      await apiJson(`/api/download/${id}`, { method: "DELETE" });
      setDownloads((current) => current.filter((item) => item.id !== id));
      toast("下载任务已删除");
    } catch (error) {
      toast(error instanceof Error ? error.message : "删除失败", "error");
    }
  }

  async function retryDownload(id: number) {
    try {
      await apiJson(`/api/download/${id}/retry`, { method: "POST" });
      await loadDownloads();
      toast("已重新加入下载队列");
    } catch (error) {
      toast(error instanceof Error ? error.message : "重试失败", "error");
    }
  }

  function fileSrc(item: DownloadItem) {
    if (item.status === "completed" && item.save_path) return `/api/file?path=${encodeURIComponent(item.save_path)}`;
    return item.file_type === "image" ? item.url : "";
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <SectionHeader
        eyebrow="Transfer"
        title="下载中心"
        description="所有图片、视频下载任务都会汇总到这里，后台会自动处理队列。"
        action={
          <Button variant="outline" size="sm" onClick={() => void loadDownloads()}>
            <RefreshCw className="h-4 w-4" />
            刷新
          </Button>
        }
      />

      {downloads.length ? (
        <div className="space-y-3">
          {downloads.map((item, index) => {
            const src = fileSrc(item);
            const badge = downloadBadge(item.status);
            return (
              <article key={item.id} className="panel-tight motion-card p-3" style={{ animationDelay: `${Math.min(index, 10) * 36}ms` }}>
                <div className="grid gap-3 lg:grid-cols-[96px_minmax(0,1fr)_auto] lg:items-center">
                  <button
                    className="media-checker flex aspect-square items-center justify-center overflow-hidden rounded-md border"
                    disabled={!src}
                    onClick={() => src && setPreview({ src, type: item.file_type === "image" ? "image" : "video" })}
                  >
                    {src ? (
                      item.file_type === "image" ? (
                        <img src={src} alt={item.file_name} className="h-full w-full object-cover" />
                      ) : (
                        <video src={src} preload="metadata" muted className="h-full w-full bg-black object-cover" />
                      )
                    ) : (
                      <FileDown className="h-7 w-7 text-muted-foreground" />
                    )}
                  </button>
                  <div className="min-w-0 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate text-sm font-semibold">{truncate(item.file_name, 100)}</div>
                      <Badge variant={badge.variant}>{badge.label}</Badge>
                    </div>
                    <div className="space-y-1">
                      <Progress value={item.progress || 0} />
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>{item.file_type} / {formatTime(item.created_at)}</span>
                        <span>{item.progress || 0}%</span>
                      </div>
                    </div>
                    <div className="truncate text-xs text-muted-foreground">{item.save_path || item.url}</div>
                  </div>
                  <div className="flex flex-wrap gap-2 lg:justify-end">
                    <Button variant="outline" size="sm" disabled={!src} onClick={() => src && setPreview({ src, type: item.file_type === "image" ? "image" : "video" })}>
                      预览
                    </Button>
                    {item.status === "failed" ? (
                      <Button variant="outline" size="sm" onClick={() => void retryDownload(item.id)}>
                        <RotateCcw className="h-4 w-4" />
                        重试
                      </Button>
                    ) : null}
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => void deleteDownload(item.id)}>
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
        <EmptyState icon={<DownloadCloud className="h-6 w-6" />} title="暂无下载任务" description="在图片、视频或历史页面点击下载后，队列会显示进度。" />
      )}

      {preview ? (
        <PreviewDialog
          src={preview.src}
          type={preview.type}
          title="文件预览"
          onOpenChange={(open) => {
            if (!open) setPreview(null);
          }}
        />
      ) : null}
    </div>
  );
}
