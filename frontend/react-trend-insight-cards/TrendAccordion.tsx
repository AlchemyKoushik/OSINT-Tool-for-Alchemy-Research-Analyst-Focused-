"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useId } from "react";

import type { Trend } from "./types";
import { Button } from "./ui/button";
import { Separator } from "./ui/separator";
import { TrendExamples } from "./TrendExamples";
import { TrendSources } from "./TrendSources";

type TrendAccordionProps = {
  isOpen: boolean;
  onToggle: () => void;
  examples?: Trend["examples"];
  sources: Trend["sources"];
  reducedMotion?: boolean;
};

const transition = {
  duration: 0.24,
  ease: [0.22, 1, 0.36, 1] as const,
};

export function TrendAccordion({
  isOpen,
  onToggle,
  examples,
  sources,
  reducedMotion = false,
}: TrendAccordionProps) {
  const contentId = useId();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4 border-t border-slate-200/80 pt-4 dark:border-slate-800">
        <div className="flex items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
          <span className="font-medium">{sources.length} sources</span>
        </div>
        <Button
          type="button"
          variant="ghost"
          onClick={onToggle}
          aria-expanded={isOpen}
          aria-controls={contentId}
          className="group inline-flex min-h-11 rounded-full border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition-all duration-200 hover:border-emerald-900/20 hover:bg-emerald-950/[0.03] hover:text-emerald-950 focus-visible:ring-2 focus-visible:ring-emerald-800 focus-visible:ring-offset-2 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 dark:hover:border-emerald-700/30 dark:hover:bg-emerald-500/10 dark:hover:text-emerald-200 dark:focus-visible:ring-emerald-400 dark:focus-visible:ring-offset-slate-950"
        >
          {isOpen ? "Hide" : "Show"}
          <ChevronDown
            className={`ml-2 h-4 w-4 transition-transform duration-200 ${
              isOpen ? "rotate-180" : ""
            }`}
          />
        </Button>
      </div>

      <AnimatePresence initial={false}>
        {isOpen ? (
          <motion.section
            id={contentId}
            key="accordion-content"
            initial={reducedMotion ? false : { opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={reducedMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
            transition={transition}
            className="overflow-hidden"
          >
            <div className="space-y-6 pb-1">
              <section className="space-y-3">
                <div className="space-y-1">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    Recent Examples
                  </p>
                  <Separator className="bg-slate-200 dark:bg-slate-800" />
                </div>
                <TrendExamples
                  examples={examples}
                  reducedMotion={reducedMotion}
                />
              </section>

              <section className="space-y-3">
                <div className="space-y-1">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                    Sources
                  </p>
                  <Separator className="bg-slate-200 dark:bg-slate-800" />
                </div>
                <TrendSources sources={sources} />
              </section>
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
