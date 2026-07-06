import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionHeader, Field } from "@/components/studio/StudioPrimitives";
import { useToast } from "@/components/studio/ToastProvider";
import { apiJson, type ConfigResponse } from "@/lib/api";

type SettingsPageProps = {
  onConfigured?: (configured: boolean) => void;
};

export function SettingsPage({ onConfigured }: SettingsPageProps) {
  const toast = useToast();
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://apihub.agnes-ai.com/v1");
  const [preview, setPreview] = useState("");
  const [configured, setConfigured] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void loadConfig();
  }, []);

  async function loadConfig() {
    try {
      const data = await apiJson<ConfigResponse>("/api/config");
      setApiKey("");
      setBaseUrl(data.base_url || "https://apihub.agnes-ai.com/v1");
      setPreview(data.api_key_preview || "");
      setConfigured(Boolean(data.configured));
      onConfigured?.(Boolean(data.configured));
    } catch (error) {
      toast(error instanceof Error ? error.message : "读取配置失败", "error");
    }
  }

  async function saveConfig() {
    if (!apiKey.trim() && !configured) {
      toast("请输入 API Key", "error");
      return;
    }
    setSaving(true);
    try {
      await apiJson("/api/config", {
        method: "POST",
        body: JSON.stringify({
          api_key: apiKey.trim(),
          base_url: baseUrl.trim() || "https://apihub.agnes-ai.com/v1",
        }),
      });
      setConfigured(true);
      onConfigured?.(true);
      setPreview(apiKey.trim() ? `${apiKey.trim().slice(0, 4)}...${apiKey.trim().slice(-4)}` : preview);
      setApiKey("");
      toast("配置已保存");
    } catch (error) {
      toast(error instanceof Error ? error.message : "保存失败", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <SectionHeader eyebrow="Preferences" title="设置" description="配置 API Key 和 Agnes API 服务地址。保存时会执行一次验证请求。" />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,620px)_minmax(280px,1fr)]">
        <section className="panel motion-panel p-5">
          <div className="mb-5 flex items-center gap-3">
            <div className="rounded-md border bg-muted p-3">
              <KeyRound className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h3 className="text-sm font-semibold">API 配置</h3>
              <p className="text-xs text-muted-foreground">留空 API Key 时会沿用已保存的密钥。</p>
            </div>
          </div>
          <div className="space-y-4">
            <Field label="API Key">
              <Input
                value={apiKey}
                type="password"
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={preview ? `已保存：${preview}` : "输入你的 API Key"}
                autoComplete="off"
              />
            </Field>
            <Field label="Base URL">
              <Input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://apihub.agnes-ai.com/v1" />
            </Field>
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={saveConfig} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? "验证中" : "保存配置"}
              </Button>
              <a className="text-sm font-semibold text-primary hover:underline" href="https://agnes-ai.com/" target="_blank" rel="noreferrer">
                获取 Key
              </a>
            </div>
          </div>
        </section>

        <aside className="panel-tight motion-panel h-fit p-5" style={{ animationDelay: "90ms" }}>
          <div className="flex items-start gap-3">
            <CheckCircle2 className={configured ? "h-5 w-5 text-primary" : "h-5 w-5 text-muted-foreground"} />
            <div>
              <div className="text-sm font-semibold">{configured ? "已配置" : "尚未配置"}</div>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">
                {configured
                  ? "当前工作台可以使用图片、视频和对话功能。修改配置后会重新验证。"
                  : "首次使用需要保存 API Key。验证通过后会进入完整工作台。"}
              </p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
