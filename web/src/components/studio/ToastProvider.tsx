import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

import { cn } from "@/lib/utils";

type ToastType = "success" | "error" | "info";

type Toast = {
  id: number;
  message: string;
  type: ToastType;
};

type ToastContextValue = {
  toast: (message: string, type?: ToastType) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const toast = useCallback(
    (message: string, type: ToastType = "success") => {
      const id = Date.now() + Math.round(Math.random() * 1000);
      setToasts((current) => [...current, { id, message, type }]);
      window.setTimeout(() => dismiss(id), 3600);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed right-4 top-4 z-[80] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((item) => {
          const Icon = item.type === "error" ? AlertCircle : item.type === "info" ? Info : CheckCircle2;
          return (
            <div
              key={item.id}
              className={cn(
                "toast-card flex items-start gap-3 rounded-lg border bg-card px-3 py-3 text-sm shadow-crisp",
                item.type === "error" && "border-destructive/30",
                item.type === "success" && "border-primary/30",
              )}
            >
              <Icon
                className={cn(
                  "mt-0.5 h-4 w-4 flex-none",
                  item.type === "error" ? "text-destructive" : item.type === "success" ? "text-primary" : "text-studio-steel",
                )}
              />
              <div className="min-w-0 flex-1 leading-5">{item.message}</div>
              <button className="rounded-sm p-0.5 text-muted-foreground hover:text-foreground" onClick={() => dismiss(item.id)}>
                <X className="h-3.5 w-3.5" />
                <span className="sr-only">关闭</span>
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside ToastProvider");
  return context.toast;
}
