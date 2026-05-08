import type { HTMLAttributes } from "react";

import { cn } from "./utils";

type BadgeProps = HTMLAttributes<HTMLDivElement> & {
  variant?: "default" | "secondary";
};

export function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold transition-colors",
        variant === "secondary"
          ? "border-transparent bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-slate-100"
          : "border-slate-200 bg-white text-slate-900 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100",
        className,
      )}
      {...props}
    />
  );
}
