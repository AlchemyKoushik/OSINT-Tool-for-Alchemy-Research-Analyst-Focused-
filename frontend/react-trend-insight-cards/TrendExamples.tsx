"use client";

import { motion } from "framer-motion";

import { Badge } from "./ui/badge";

type TrendExamplesProps = {
  examples?: {
    text: string;
    year?: string;
  }[];
  reducedMotion?: boolean;
};

const itemTransition = {
  duration: 0.22,
  ease: [0.22, 1, 0.36, 1] as const,
};

export function TrendExamples({
  examples,
  reducedMotion = false,
}: TrendExamplesProps) {
  if (!examples?.length) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300/90 bg-slate-50/80 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-400">
        No recent examples were attached to this trend yet.
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {examples.map((example, index) => (
        <motion.article
          key={`${example.text}-${index}`}
          initial={reducedMotion ? false : { opacity: 0, y: 10 }}
          animate={reducedMotion ? {} : { opacity: 1, y: 0 }}
          transition={{
            ...itemTransition,
            delay: reducedMotion ? 0 : index * 0.04,
          }}
          className="group rounded-2xl border border-slate-200/90 bg-white/95 p-4 shadow-[0_8px_24px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-0.5 hover:border-emerald-900/20 hover:shadow-[0_14px_32px_rgba(15,23,42,0.08)] dark:border-slate-800 dark:bg-slate-950/70 dark:hover:border-emerald-700/30"
        >
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm leading-6 text-slate-700 dark:text-slate-200">
              {example.text}
            </p>
            {example.year ? (
              <Badge
                variant="secondary"
                className="shrink-0 rounded-full border border-emerald-900/10 bg-emerald-900/[0.05] px-2.5 py-1 text-[11px] font-semibold tracking-[0.12em] text-emerald-950 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200"
              >
                {example.year}
              </Badge>
            ) : null}
          </div>
        </motion.article>
      ))}
    </div>
  );
}
