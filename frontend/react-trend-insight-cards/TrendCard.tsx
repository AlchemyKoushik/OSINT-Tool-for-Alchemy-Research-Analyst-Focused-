"use client";

import { motion, useReducedMotion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { useState } from "react";

import { TrendAccordion } from "./TrendAccordion";
import type { Trend } from "./types";
import { Badge } from "./ui/badge";
import { Card, CardContent } from "./ui/card";

type TrendCardProps = {
  trend: Trend;
  defaultExpanded?: boolean;
};

const cardTransition = {
  duration: 0.28,
  ease: [0.22, 1, 0.36, 1] as const,
};

export function TrendCard({
  trend,
  defaultExpanded = false,
}: TrendCardProps) {
  const [isOpen, setIsOpen] = useState(defaultExpanded);
  const reducedMotion = useReducedMotion();

  return (
    <motion.div
      initial={reducedMotion ? false : { opacity: 0, y: 20 }}
      animate={reducedMotion ? {} : { opacity: 1, y: 0 }}
      transition={cardTransition}
      className="h-full"
    >
      <Card className="group h-full rounded-[1.75rem] border border-slate-200/80 bg-white shadow-[0_10px_32px_rgba(15,23,42,0.05)] transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_20px_48px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_14px_40px_rgba(2,6,23,0.45)]">
        <CardContent className="flex h-full flex-col gap-6 p-5 sm:p-7">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full border border-emerald-900/10 bg-emerald-950 text-sm font-semibold text-white shadow-sm dark:border-emerald-500/20 dark:bg-emerald-800">
                {String(trend.id).padStart(2, "0")}
              </div>
              <div className="space-y-2">
                <Badge
                  variant="secondary"
                  className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold tracking-[0.18em] text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
                >
                  TREND
                </Badge>
                <h3 className="max-w-3xl text-balance text-xl font-semibold leading-tight tracking-[-0.02em] text-slate-950 sm:text-[1.4rem] dark:text-white">
                  {trend.title}
                </h3>
              </div>
            </div>

            <div className="hidden rounded-full border border-emerald-900/10 bg-emerald-900/[0.04] p-2 text-emerald-900 sm:block dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300">
              <Sparkles className="h-4 w-4" />
            </div>
          </div>

          <div className="flex-1">
            <p className="max-w-none text-pretty text-[15px] leading-7 text-slate-700 sm:text-base dark:text-slate-200">
              {trend.description}
            </p>
          </div>

          <TrendAccordion
            isOpen={isOpen}
            onToggle={() => setIsOpen((open) => !open)}
            examples={trend.examples}
            sources={trend.sources}
            reducedMotion={Boolean(reducedMotion)}
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}
