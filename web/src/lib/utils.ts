import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTime(value?: string | number | null) {
  if (!value) return "刚刚";
  if (typeof value === "number" || (typeof value === "string" && /^\d{10,}$/.test(value))) {
    return new Date(Number(value) * 1000).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function truncate(value: string | undefined | null, length = 80) {
  const text = String(value || "");
  return text.length > length ? `${text.slice(0, length)}...` : text;
}

export function localFileUrl(path?: string | null) {
  if (!path) return "";
  return `/api/file?path=${encodeURIComponent(path)}`;
}

export function mediaSource(item: { local_path?: string | null; url?: string | null }) {
  return item.local_path ? localFileUrl(item.local_path) : item.url || "";
}

export function downloadSource(item: { local_path?: string | null; url?: string | null }) {
  if (item.url) return item.url;
  const src = mediaSource(item);
  return src.startsWith("/") ? `${window.location.origin}${src}` : src;
}

export async function fileToDataUri(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch("/api/upload-image", { method: "POST", body: formData });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(error.detail || error.message || "上传失败");
  }
  const data = (await response.json()) as { data_uri?: string };
  return data.data_uri || "";
}

export function playableVideoUrl(taskId?: string | null, resultUrl?: string | null) {
  if (taskId && resultUrl?.includes("storage.googleapis.com")) return `/api/video/stream/${taskId}`;
  return resultUrl || "";
}

export function isVideoStatusActive(status?: string | null) {
  return [
    "queued",
    "pending",
    "submitted",
    "starting",
    "started",
    "waiting",
    "inference",
    "in_progress",
    "processing",
    "running",
    "generating",
    "rendering",
  ].includes(String(status || "").toLowerCase());
}
