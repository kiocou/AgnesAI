import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** 渲染 AI 回答的 Markdown 内容（GFM：表格/任务列表/删除线；不渲染原始 HTML，防 XSS） */
export function Markdown({ content }: { content: string }) {
  return (
    <div className="markdown-body text-sm leading-6">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
