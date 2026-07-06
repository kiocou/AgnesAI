import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  ImagePlus,
  Loader2,
  MessageSquarePlus,
  RefreshCw,
  Send,
  Settings2,
  Square,
  Trash2,
  Wand2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, Field } from "@/components/studio/StudioPrimitives";
import { useToast } from "@/components/studio/ToastProvider";
import {
  apiJson,
  defaultSystemPrompt,
  type ChatContentPart,
  type ChatMessage,
  type ConversationDetail,
  type ConversationSummary,
} from "@/lib/api";
import { cn, formatTime, truncate } from "@/lib/utils";

type PendingImage = {
  dataUri: string;
  name: string;
};

type ToolActivity = {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: Record<string, unknown>;
};

type UiMessage = {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  images?: string[];
  tools?: ToolActivity[];
};

function readFileAsDataUri(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("图片读取失败"));
    reader.readAsDataURL(file);
  });
}

function messageText(content: ChatMessage["content"]) {
  if (Array.isArray(content)) {
    return content
      .filter((part): part is Extract<ChatContentPart, { type: "text" }> => part.type === "text")
      .map((part) => part.text)
      .join("\n");
  }
  return String(content || "");
}

function messageImages(content: ChatMessage["content"]) {
  if (!Array.isArray(content)) return [];
  return content
    .filter((part): part is Extract<ChatContentPart, { type: "image_url" }> => part.type === "image_url")
    .map((part) => part.image_url?.url)
    .filter(Boolean);
}

function conversationTitle(messages: ChatMessage[]) {
  const firstUser = messages.find((message) => message.role === "user");
  const title = firstUser ? messageText(firstUser.content).trim() : "";
  return truncate(title || "新对话", 60);
}

function toolLabel(name: string) {
  if (name === "generate_image") return "生成图片";
  if (name === "generate_video") return "生成视频";
  return name || "工具调用";
}

export function ChatPage() {
  const toast = useToast();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<number | null>(null);
  const [conversation, setConversation] = useState<ChatMessage[]>([]);
  const [uiMessages, setUiMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [model, setModel] = useState("agnes-2.0-flash");
  const [temperature, setTemperature] = useState("0.7");
  const [topP, setTopP] = useState("0.95");
  const [maxTokens, setMaxTokens] = useState("4096");
  const [systemPrompt, setSystemPrompt] = useState(defaultSystemPrompt);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const hasMessages = uiMessages.length > 0;

  useEffect(() => {
    void loadConversations();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [uiMessages, streaming]);

  async function loadConversations() {
    try {
      const data = await apiJson<{ conversations: ConversationSummary[] }>("/api/chat/conversations");
      setConversations(data.conversations || []);
    } catch (error) {
      console.warn(error);
    }
  }

  function startNewChat() {
    if (streaming) abortRef.current?.abort();
    setCurrentConversationId(null);
    setConversation([]);
    setUiMessages([]);
    setInput("");
    setPendingImages([]);
    setStreaming(false);
  }

  async function loadConversation(id: number) {
    if (streaming) return;
    try {
      const detail = await apiJson<ConversationDetail>(`/api/chat/conversations/${id}`);
      setCurrentConversationId(detail.id);
      setConversation(detail.messages || []);
      setModel(detail.model || "agnes-2.0-flash");
      setUiMessages(
        (detail.messages || [])
          .filter((message) => message.role === "user" || message.role === "assistant")
          .map((message, index) => ({
            id: `${detail.id}-${index}`,
            role: message.role as "user" | "assistant",
            content: messageText(message.content),
            images: messageImages(message.content),
          })),
      );
      void loadConversations();
    } catch (error) {
      toast(error instanceof Error ? error.message : "加载对话失败", "error");
    }
  }

  async function deleteConversation(id: number) {
    try {
      await apiJson(`/api/chat/conversations/${id}`, { method: "DELETE" });
      if (id === currentConversationId) startNewChat();
      await loadConversations();
      toast("对话已删除");
    } catch (error) {
      toast(error instanceof Error ? error.message : "删除失败", "error");
    }
  }

  async function handleImageFiles(files: FileList | null) {
    if (!files) return;
    try {
      const images: PendingImage[] = [];
      for (const file of Array.from(files)) {
        if (!file.type.startsWith("image/")) continue;
        images.push({ dataUri: await readFileAsDataUri(file), name: file.name });
      }
      setPendingImages((current) => [...current, ...images]);
    } catch (error) {
      toast(error instanceof Error ? error.message : "图片上传失败", "error");
    }
  }

  async function saveConversation(nextConversation: ChatMessage[], conversationId = currentConversationId) {
    if (!nextConversation.length) return;
    try {
      const data = await apiJson<{ conversation_id: number }>("/api/chat/save", {
        method: "POST",
        body: JSON.stringify({
          conversation_id: conversationId,
          title: conversationTitle(nextConversation),
          messages: nextConversation,
          model,
        }),
      });
      setCurrentConversationId(data.conversation_id);
      await loadConversations();
    } catch (error) {
      console.warn(error);
    }
  }

  async function sendMessage() {
    const text = input.trim();
    if ((!text && !pendingImages.length) || streaming) return;

    const userContent: string | ChatContentPart[] = pendingImages.length
      ? [
          ...pendingImages.map((image) => ({ type: "image_url" as const, image_url: { url: image.dataUri } })),
          { type: "text" as const, text: text || "请分析这张图片，并根据它继续创作。" },
        ]
      : text;

    const userMessage: ChatMessage = { role: "user", content: userContent };
    const nextConversation = [...conversation, userMessage];
    const userUi: UiMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: pendingImages.length ? text || "请分析这张图片，并根据它继续创作。" : text,
      images: pendingImages.map((image) => image.dataUri),
    };
    const assistantId = `assistant-${Date.now()}`;
    setConversation(nextConversation);
    setUiMessages((current) => [...current, userUi, { id: assistantId, role: "assistant", content: "", tools: [] }]);
    setInput("");
    setPendingImages([]);
    setStreaming(true);

    const requestMessages: ChatMessage[] = systemPrompt.trim()
      ? [{ role: "system", content: systemPrompt.trim() }, ...nextConversation]
      : nextConversation;

    const abort = new AbortController();
    abortRef.current = abort;
    let accumulated = "";

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: requestMessages,
          model,
          temperature: Number(temperature) || 0.7,
          top_p: Number(topP) || 0.95,
          max_tokens: Number(maxTokens) || 4096,
          stream: true,
          use_tools: true,
        }),
        signal: abort.signal,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || error.message || "请求失败");
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("浏览器不支持流式读取");
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (!payload || payload === "[DONE]") continue;
          const chunk = JSON.parse(payload) as {
            delta?: string;
            error?: string;
            tool_start?: { name: string; args?: Record<string, unknown> };
            tool_result?: { name: string; result?: Record<string, unknown> };
          };

          if (chunk.error) throw new Error(chunk.error);

          if (chunk.tool_start) {
            const tool: ToolActivity = {
              id: `tool-${Date.now()}-${Math.random()}`,
              name: chunk.tool_start.name,
              args: chunk.tool_start.args,
              status: "running",
            };
            setUiMessages((current) =>
              current.map((message) =>
                message.id === assistantId ? { ...message, tools: [...(message.tools || []), tool] } : message,
              ),
            );
          }

          if (chunk.tool_result) {
            setUiMessages((current) =>
              current.map((message) => {
                if (message.id !== assistantId) return message;
                const tools = [...(message.tools || [])];
                const index = [...tools].reverse().findIndex((tool) => tool.name === chunk.tool_result?.name && tool.status === "running");
                const realIndex = index >= 0 ? tools.length - 1 - index : tools.length - 1;
                if (realIndex >= 0) {
                  const result = chunk.tool_result?.result || {};
                  tools[realIndex] = {
                    ...tools[realIndex],
                    status: result.success === false ? "error" : "success",
                    result,
                  };
                }
                return { ...message, tools };
              }),
            );
          }

          if (chunk.delta) {
            accumulated += chunk.delta;
            setUiMessages((current) =>
              current.map((message) => (message.id === assistantId ? { ...message, content: accumulated } : message)),
            );
          }
        }
      }

      const assistantMessage: ChatMessage = { role: "assistant", content: accumulated || "已完成工具调用。" };
      const finalConversation = [...nextConversation, assistantMessage];
      setConversation(finalConversation);
      setUiMessages((current) =>
        current.map((message) =>
          message.id === assistantId && !message.content ? { ...message, content: assistantMessage.content as string } : message,
        ),
      );
      void saveConversation(finalConversation);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        if (accumulated) {
          const assistantMessage: ChatMessage = { role: "assistant", content: `${accumulated}\n\n[已停止]` };
          const finalConversation = [...nextConversation, assistantMessage];
          setConversation(finalConversation);
          void saveConversation(finalConversation);
        } else {
          setUiMessages((current) => current.filter((message) => message.id !== assistantId));
        }
      } else {
        setUiMessages((current) => [
          ...current.filter((message) => message.id !== assistantId),
          { id: `error-${Date.now()}`, role: "error", content: error instanceof Error ? error.message : "对话请求失败" },
        ]);
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  const conversationMeta = useMemo(() => {
    if (!conversation.length) return "新对话";
    return `${conversation.filter((message) => message.role === "user").length} 轮对话`;
  }, [conversation]);

  return (
    <div className="grid h-full min-h-0 gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="panel motion-panel flex min-h-0 flex-col p-3">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <div className="text-sm font-semibold">历史对话</div>
            <div className="text-xs text-muted-foreground">{conversationMeta}</div>
          </div>
          <div className="flex gap-1">
            <Button variant="ghost" size="icon" onClick={startNewChat} title="新建对话">
              <MessageSquarePlus className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" onClick={() => void loadConversations()} title="刷新">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {conversations.length ? (
            conversations.map((item, index) => (
              <div
                key={item.id}
                className={cn(
                  "motion-card group flex items-center gap-2 rounded-md border px-3 py-2 transition hover:border-primary hover:bg-primary/5",
                  item.id === currentConversationId && "border-primary bg-primary/10",
                )}
                style={{ animationDelay: `${Math.min(index, 8) * 35}ms` }}
              >
                <button className="min-w-0 flex-1 text-left" onClick={() => void loadConversation(item.id)}>
                  <div className="truncate text-sm font-semibold">{item.title || "新对话"}</div>
                  <div className="text-xs text-muted-foreground">
                    {item.message_count || 0} 条 / {formatTime(item.updated_at)}
                  </div>
                </button>
                <button
                  type="button"
                  className="rounded-sm p-1 text-muted-foreground opacity-0 transition hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 focus:opacity-100"
                  onClick={() => void deleteConversation(item.id)}
                  title="删除对话"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  <span className="sr-only">删除对话</span>
                </button>
              </div>
            ))
          ) : (
            <EmptyState title="暂无对话" description="开始聊天后会自动保存到这里。" className="min-h-[180px]" />
          )}
        </div>
      </aside>

      <section className="panel motion-panel flex min-h-0 flex-col overflow-hidden" style={{ animationDelay: "60ms" }}>
        <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="rounded-md border bg-muted p-2">
              <Bot className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h2 className="text-sm font-semibold">Agnes-2.0-Flash</h2>
              <p className="text-xs text-muted-foreground">流式对话 / 图片理解 / 工具调用</p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => setSettingsOpen(true)}>
            <Settings2 className="h-4 w-4" />
            设置
          </Button>
        </header>

        <div className="grid-paper min-h-0 flex-1 overflow-y-auto p-4">
          {hasMessages ? (
            <div className="mx-auto flex max-w-4xl flex-col gap-4">
              {uiMessages.map((message, index) => (
                <ChatBubble key={message.id} message={message} index={index} />
              ))}
              <div ref={scrollRef} />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-md text-center">
                <div className="upload-icon mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-lg border bg-card shadow-sm">
                  <Wand2 className="h-7 w-7 text-primary" />
                </div>
                <h2 className="font-display text-2xl font-bold">开始一个创作对话</h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  你可以直接让 Agnes 写提示词、分析图片，或在对话中生成图片和视频。
                </p>
              </div>
            </div>
          )}
        </div>

        <footer className="border-t bg-card p-3">
          {pendingImages.length ? (
            <div className="mb-3 flex flex-wrap gap-2">
              {pendingImages.map((image, index) => (
                <div key={`${image.name}-${index}`} className="motion-thumb group relative h-16 w-16 overflow-hidden rounded-md border bg-muted">
                  <img src={image.dataUri} alt={image.name} className="h-full w-full object-cover" />
                  <button
                    className="absolute right-1 top-1 rounded-full bg-studio-ink/75 p-1 text-white opacity-0 transition group-hover:opacity-100"
                    onClick={() => setPendingImages((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          <div className="flex items-end gap-2">
            <label className="flex h-10 w-10 cursor-pointer items-center justify-center rounded-md border bg-background transition hover:bg-accent hover:text-accent-foreground" title="上传图片">
              <ImagePlus className="h-4 w-4" />
              <input
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={(event) => {
                  void handleImageFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </label>
            <Textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              placeholder="输入消息... Enter 发送，Shift + Enter 换行"
              className="max-h-40 min-h-10 resize-none py-2"
              rows={1}
            />
            {streaming ? (
              <Button variant="destructive" onClick={() => abortRef.current?.abort()}>
                <Square className="h-4 w-4" />
                停止
              </Button>
            ) : (
              <Button onClick={() => void sendMessage()} disabled={!input.trim() && !pendingImages.length}>
                <Send className="h-4 w-4" />
                发送
              </Button>
            )}
          </div>
        </footer>
      </section>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>对话设置</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <Field label="模型">
              <Select value={model} onValueChange={setModel}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="agnes-2.0-flash">agnes-2.0-flash</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Field label="Temperature">
                <Input value={temperature} onChange={(event) => setTemperature(event.target.value)} type="number" min="0" max="1.5" step="0.1" />
              </Field>
              <Field label="Top P">
                <Input value={topP} onChange={(event) => setTopP(event.target.value)} type="number" min="0" max="1" step="0.05" />
              </Field>
              <Field label="Max Tokens">
                <Input value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} type="number" min="256" max="65536" step="256" />
              </Field>
            </div>
            <Field label="System Prompt">
              <Textarea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} className="min-h-[220px]" />
            </Field>
          </div>
          <DialogFooter>
            <Button onClick={() => setSettingsOpen(false)}>完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ChatBubble({ message, index = 0 }: { message: UiMessage; index?: number }) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  return (
    <div className={cn("motion-chat flex", isUser ? "justify-end" : "justify-start")} style={{ animationDelay: `${Math.min(index, 12) * 24}ms` }}>
      <div
        className={cn(
          "max-w-[min(760px,88%)] rounded-lg border bg-card px-4 py-3 shadow-sm transition-all duration-200 hover:border-primary/40 hover:shadow-crisp",
          isUser && "border-primary/30 bg-primary/10",
          isError && "border-destructive/30 bg-destructive/10 text-destructive",
        )}
      >
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {isUser ? "你" : isError ? "错误" : "Agnes"}
        </div>
        {message.images?.length ? (
          <div className="mb-2 flex flex-wrap gap-2">
            {message.images.map((src, index) => (
              <img key={`${src}-${index}`} src={src} alt="uploaded" className="h-28 w-28 rounded-md border object-cover" />
            ))}
          </div>
        ) : null}
        {message.tools?.length ? (
          <div className="mb-2 space-y-2">
            {message.tools.map((tool) => (
              <div key={tool.id} className="motion-card rounded-md border bg-muted/45 p-3">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  {tool.status === "running" ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : <Wand2 className="h-4 w-4 text-primary" />}
                  {toolLabel(tool.name)}
                </div>
                {typeof tool.args?.prompt === "string" ? (
                  <div className="mt-1 text-xs leading-5 text-muted-foreground">{truncate(tool.args.prompt, 120)}</div>
                ) : null}
                {tool.result ? <ToolResult tool={tool} /> : null}
              </div>
            ))}
          </div>
        ) : null}
        <div className="whitespace-pre-wrap text-sm leading-6">
          {message.content || (!isUser && !isError ? <span className="inline-flex items-center gap-2 text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />思考中</span> : null)}
        </div>
      </div>
    </div>
  );
}

function ToolResult({ tool }: { tool: ToolActivity }) {
  const result = tool.result || {};
  if (tool.status === "error") {
    return <div className="mt-2 rounded-md bg-destructive/10 px-2 py-1 text-xs text-destructive">{String(result.message || "工具调用失败")}</div>;
  }
  if (tool.name === "generate_image" && typeof result.image_url === "string") {
    return <img src={result.image_url} alt="tool result" className="mt-2 max-h-72 rounded-md border object-contain" />;
  }
  if (tool.name === "generate_video" && typeof result.task_id === "string") {
    return <div className="mt-2 rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">视频任务已创建：{result.task_id.slice(0, 12)}</div>;
  }
  return <div className="mt-2 rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">工具调用完成</div>;
}
