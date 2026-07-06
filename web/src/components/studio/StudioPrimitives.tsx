import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block min-w-0 space-y-2", className)}>
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div className={cn("motion-panel flex min-h-[220px] flex-col items-center justify-center rounded-lg border border-dashed bg-muted/30 p-8 text-center", className)}>
      {icon ? <div className="mb-3 rounded-md border bg-background p-3 text-muted-foreground shadow-sm">{icon}</div> : null}
      <div className="text-sm font-semibold">{title}</div>
      {description ? <div className="mt-1 max-w-sm text-xs leading-5 text-muted-foreground">{description}</div> : null}
    </div>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="motion-panel mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {eyebrow ? <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">{eyebrow}</div> : null}
        <h2 className="font-display text-2xl font-bold leading-tight">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-6 text-muted-foreground">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}
