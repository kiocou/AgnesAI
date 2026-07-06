export type ConfigResponse = {
  api_key: string;
  api_key_preview?: string;
  base_url: string;
  configured: boolean;
};

export type ImageItem = {
  url?: string;
  local_path?: string;
  prompt?: string;
  created_at?: string;
};

export type VideoTask = {
  id?: number;
  task_id: string;
  video_id?: string;
  status: string;
  progress: number;
  created_at?: string;
  prompt: string;
  negative_prompt?: string;
  model?: string;
  mode?: string;
  resolution?: string;
  duration_seconds?: number;
  fps?: number;
  result_url?: string;
  local_path?: string;
  completed_at?: string;
  error?: string;
};

export type DownloadItem = {
  id: number;
  file_name: string;
  file_type: "image" | "video" | string;
  size: number;
  progress: number;
  status: string;
  save_path: string;
  url: string;
  created_at?: string;
  updated_at?: string;
};

export type HistoryRecord = {
  id: number;
  kind: "image" | "video";
  created_at: string;
  model: string;
  prompt: string;
  negative_prompt?: string;
  meta?: string;
  result_url?: string;
  result_urls?: string[];
  local_path?: string;
  local_paths?: string[];
  status?: string;
  size?: string;
  count?: number;
  seed?: string;
  task_id?: string;
  video_id?: string;
  mode?: string;
  resolution?: string;
  duration_seconds?: number;
  fps?: number;
  images?: ImageItem[];
};

export type ConversationSummary = {
  id: number;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type ChatContentPart =
  | { type: "text"; text: string }
  | { type: "image_url"; image_url: { url: string } };

export type ChatMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | ChatContentPart[];
  tool_call_id?: string;
  tool_calls?: unknown[];
};

export type ConversationDetail = ConversationSummary & {
  messages: ChatMessage[];
};

export async function apiJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || error.message || "请求失败");
  }
  return response.json() as Promise<T>;
}

export function imageItemsFromRecord(record: HistoryRecord): ImageItem[] {
  if (Array.isArray(record.images) && record.images.length) {
    return record.images.filter((item) => item.url || item.local_path);
  }

  const urls = Array.isArray(record.result_urls)
    ? record.result_urls
    : String(record.result_url || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
  const paths = Array.isArray(record.local_paths)
    ? record.local_paths
    : String(record.local_path || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);

  const count = Math.max(urls.length, paths.length, Number(record.count || 0));
  const items: ImageItem[] = [];
  for (let index = 0; index < count; index += 1) {
    const item = { url: urls[index] || "", local_path: paths[index] || "" };
    if (item.url || item.local_path) items.push(item);
  }
  return items;
}

export const defaultSystemPrompt = `You are a helpful AI assistant powered by Agnes-2.0-Flash. You can generate images and videos using the available tools. When the user asks to create, draw, or generate visual content, use the appropriate tool (generate_image or generate_video) with a detailed English prompt.

IMPORTANT - Image-to-Image (img2img) workflow: When the user uploads a reference image and asks you to recreate, transform, restyle, or generate something similar, you should:
1. Carefully analyze the uploaded image (composition, subject, colors, style, mood)
2. Create a very detailed English prompt that describes a NEW image inspired by the reference, preserving key elements like composition, subject pose, color palette, and mood
3. Call the generate_image tool with your detailed prompt
4. The user wants the output to be visually similar to their reference but generated fresh

Always respond in the same language as the user.`;
