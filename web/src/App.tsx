import { useEffect, useState, type ReactNode } from "react";
import {
  Download,
  History,
  ImageIcon,
  KeyRound,
  MessageSquare,
  Moon,
  Settings,
  Sparkles,
  Sun,
  Video,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider, useToast } from "@/components/studio/ToastProvider";
import { ChatPage } from "@/pages/ChatPage";
import { DownloadPage } from "@/pages/DownloadPage";
import { HistoryPage } from "@/pages/HistoryPage";
import { ImagePage } from "@/pages/ImagePage";
import { SettingsPage } from "@/pages/SettingsPage";
import { VideoPage } from "@/pages/VideoPage";
import { apiJson, type ConfigResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type PageKey = "image" | "video" | "chat" | "history" | "download" | "settings";
type Theme = "light" | "dark";

const navItems = [
  { key: "image", label: "图片生成", icon: ImageIcon, group: "create" },
  { key: "video", label: "视频生成", icon: Video, group: "create" },
  { key: "chat", label: "AI 对话", icon: MessageSquare, group: "create" },
  { key: "history", label: "历史记录", icon: History, group: "manage" },
  { key: "download", label: "下载中心", icon: Download, group: "manage" },
  { key: "settings", label: "设置", icon: Settings, group: "settings" },
] satisfies { key: PageKey; label: string; icon: typeof ImageIcon; group: string }[];

const pageTitles: Record<PageKey, { title: string; subtitle: string }> = {
  image: { title: "图片生成", subtitle: "Prompt、参考图与参数控制台" },
  video: { title: "视频生成", subtitle: "任务队列、轮询与预览" },
  chat: { title: "AI 对话", subtitle: "多轮流式对话与工具调用" },
  history: { title: "历史记录", subtitle: "生成资产归档" },
  download: { title: "下载中心", subtitle: "文件下载队列" },
  settings: { title: "设置", subtitle: "API Key 与服务地址" },
};

function getInitialTheme(): Theme {
  const saved = window.localStorage.getItem("agnes-ui-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  return (
    <ToastProvider>
      <TooltipProvider delayDuration={160}>
        <StudioApp />
      </TooltipProvider>
    </ToastProvider>
  );
}

function StudioApp() {
  const toast = useToast();
  const [page, setPage] = useState<PageKey>("image");
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme());
  const [configured, setConfigured] = useState(true);
  const [checkingConfig, setCheckingConfig] = useState(true);
  const [onboardingKey, setOnboardingKey] = useState("");
  const [onboardingUrl, setOnboardingUrl] = useState("https://apihub.agnes-ai.com/v1");
  const [savingConfig, setSavingConfig] = useState(false);

  const activeMeta = pageTitles[page];

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem("agnes-ui-theme", theme);
  }, [theme]);

  useEffect(() => {
    void loadConfig();
  }, []);

  async function loadConfig() {
    setCheckingConfig(true);
    try {
      const data = await apiJson<ConfigResponse>("/api/config");
      setConfigured(Boolean(data.configured));
      setOnboardingUrl(data.base_url || "https://apihub.agnes-ai.com/v1");
    } catch (error) {
      setConfigured(false);
      toast(error instanceof Error ? error.message : "读取配置失败", "error");
    } finally {
      setCheckingConfig(false);
    }
  }

  async function saveOnboardingConfig() {
    if (!onboardingKey.trim()) {
      toast("请输入 API Key", "error");
      return;
    }
    setSavingConfig(true);
    try {
      await apiJson("/api/config", {
        method: "POST",
        body: JSON.stringify({
          api_key: onboardingKey.trim(),
          base_url: onboardingUrl.trim() || "https://apihub.agnes-ai.com/v1",
        }),
      });
      setConfigured(true);
      setOnboardingKey("");
      toast("配置验证通过");
    } catch (error) {
      toast(error instanceof Error ? error.message : "配置保存失败", "error");
    } finally {
      setSavingConfig(false);
    }
  }

  return (
    <div className="studio-shell flex h-full min-h-0 text-foreground">
      <aside className="hidden w-[252px] flex-none border-r bg-card/88 backdrop-blur-xl lg:flex lg:flex-col">
        <div className="flex h-20 items-center gap-3 border-b px-5">
          <div className="studio-logo grid h-11 w-11 place-items-center rounded-lg bg-studio-ink text-white shadow-sm dark:bg-white dark:text-studio-ink">
            <Sparkles className="h-5 w-5 text-studio-mint" />
          </div>
          <div className="min-w-0">
            <div className="font-display text-lg font-bold leading-tight">Agnes AI</div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Creative Studio</div>
          </div>
        </div>

        <nav className="flex-1 space-y-5 overflow-y-auto p-3">
          <NavGroup label="创作">
            {navItems
              .filter((item) => item.group === "create")
              .map((item) => (
                <NavButton key={item.key} item={item} active={page === item.key} onClick={() => setPage(item.key)} />
              ))}
          </NavGroup>
          <NavGroup label="管理">
            {navItems
              .filter((item) => item.group === "manage")
              .map((item) => (
                <NavButton key={item.key} item={item} active={page === item.key} onClick={() => setPage(item.key)} />
              ))}
          </NavGroup>
          <NavGroup label="系统">
            {navItems
              .filter((item) => item.group === "settings")
              .map((item) => (
                <NavButton key={item.key} item={item} active={page === item.key} onClick={() => setPage(item.key)} />
              ))}
          </NavGroup>
        </nav>

        <div className="border-t p-4">
          <div className="rounded-lg border bg-muted/45 p-3">
            <div className="text-xs font-semibold">{configured ? "API 已就绪" : "等待配置"}</div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {configured ? "可以开始生成图片、视频和对话。" : "保存 API Key 后解锁工作台。"}
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 flex-none items-center justify-between gap-3 border-b bg-background/80 px-4 backdrop-blur-xl md:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-lg font-bold">{activeMeta.title}</h1>
            <p className="hidden truncate text-xs text-muted-foreground sm:block">{activeMeta.subtitle}</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="hidden gap-1 rounded-md border bg-card p-1 md:flex">
              {navItems.slice(0, 3).map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    className={cn(
                      "nav-pill inline-flex h-8 items-center gap-1.5 rounded-sm px-2.5 text-xs font-semibold text-muted-foreground",
                      page === item.key && "bg-primary text-primary-foreground",
                    )}
                    data-active={page === item.key}
                    onClick={() => setPage(item.key)}
                  >
                    <Icon className="nav-icon h-3.5 w-3.5" />
                    {item.label}
                  </button>
                );
              })}
            </div>
            <Button variant="outline" size="icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="切换主题">
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden p-4 md:p-5">
          <PagePanel active={page === "image"}>
            <ImagePage />
          </PagePanel>
          <PagePanel active={page === "video"}>
            <VideoPage />
          </PagePanel>
          <PagePanel active={page === "chat"}>
            <ChatPage />
          </PagePanel>
          <PagePanel active={page === "history"}>
            <HistoryPage />
          </PagePanel>
          <PagePanel active={page === "download"}>
            <DownloadPage active={page === "download"} />
          </PagePanel>
          <PagePanel active={page === "settings"}>
            <SettingsPage onConfigured={setConfigured} />
          </PagePanel>
        </main>

        <nav className="grid flex-none grid-cols-6 border-t bg-card/92 p-1.5 backdrop-blur lg:hidden">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                className={cn(
                  "nav-pill flex flex-col items-center justify-center gap-1 rounded-md px-1 py-2 text-[10px] font-semibold text-muted-foreground",
                  page === item.key && "bg-primary text-primary-foreground",
                )}
                data-active={page === item.key}
                onClick={() => setPage(item.key)}
              >
                <Icon className="nav-icon h-4 w-4" />
                <span className="max-w-full truncate">{item.label.replace("生成", "")}</span>
              </button>
            );
          })}
        </nav>
      </div>

      <Dialog open={!checkingConfig && !configured} onOpenChange={() => undefined}>
        <DialogContent showClose={false} className="max-w-md">
          <DialogHeader>
            <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-lg border bg-muted">
              <KeyRound className="h-5 w-5 text-primary" />
            </div>
            <DialogTitle>配置 API Key</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm leading-6 text-muted-foreground">首次使用需要验证 Agnes API Key。验证通过后进入完整工作台。</p>
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">API Key</span>
              <Input
                value={onboardingKey}
                onChange={(event) => setOnboardingKey(event.target.value)}
                type="password"
                autoComplete="off"
                placeholder="输入你的 API Key"
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveOnboardingConfig();
                }}
              />
            </label>
            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Base URL</span>
              <Input
                value={onboardingUrl}
                onChange={(event) => setOnboardingUrl(event.target.value)}
                placeholder="https://apihub.agnes-ai.com/v1"
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveOnboardingConfig();
                }}
              />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <Button className="flex-1" onClick={() => void saveOnboardingConfig()} disabled={savingConfig}>
                {savingConfig ? "验证中..." : "验证并进入"}
              </Button>
              <a className="text-sm font-semibold text-primary hover:underline" href="https://agnes-ai.com/" target="_blank" rel="noreferrer">
                获取 Key
              </a>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PagePanel({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <div className={cn("h-full min-h-0 overflow-y-auto overscroll-contain", active ? "page-frame block" : "hidden")} aria-hidden={!active}>
      {children}
    </div>
  );
}

function NavGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function NavButton({
  item,
  active,
  onClick,
}: {
  item: (typeof navItems)[number];
  active: boolean;
  onClick: () => void;
}) {
  const Icon = item.icon;
  return (
    <button
      className={cn(
        "nav-pill flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-muted hover:text-foreground",
        active && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
      )}
      data-active={active}
      onClick={onClick}
    >
      <Icon className="nav-icon h-4 w-4" />
      {item.label}
    </button>
  );
}
