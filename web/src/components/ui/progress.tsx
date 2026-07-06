import * as React from "react";

import { cn } from "@/lib/utils";

type ProgressProps = React.HTMLAttributes<HTMLDivElement> & {
  value?: number;
};

function Progress({ className, value = 0, ...props }: ProgressProps) {
  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full bg-muted", className)} {...props}>
      <div
        className="progress-fill h-full w-full flex-1 rounded-full"
        style={{ transform: `translateX(-${100 - Math.max(0, Math.min(100, value))}%)` }}
      />
    </div>
  );
}

export { Progress };
