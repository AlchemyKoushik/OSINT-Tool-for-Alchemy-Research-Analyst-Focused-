import type { HTMLAttributes } from "react";

import { cn } from "./utils";

export function ScrollArea({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "overflow-y-auto overscroll-contain [scrollbar-color:rgba(100,116,139,0.45)_transparent] [scrollbar-width:thin]",
        className,
      )}
      {...props}
    />
  );
}
