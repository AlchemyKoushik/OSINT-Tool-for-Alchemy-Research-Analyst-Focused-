"use client";

import { motion } from "framer-motion";
import { BarChart3, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { TrendCard } from "./TrendCard";
import { trendData } from "./trend-data";
import { Skeleton } from "./ui/skeleton";

function TrendCardSkeleton() {
  return (
    <div className="rounded-[1.75rem] border border-slate-200/80 bg-white p-6 shadow-[0_10px_32px_rgba(15,23,42,0.05)] dark:border-slate-800 dark:bg-slate-950">
      <div className="space-y-5">
        <div className="flex items-center gap-4">
          <Skeleton className="h-12 w-12 rounded-full bg-slate-200 dark:bg-slate-800" />
          <div className="flex-1 space-y-3">
            <Skeleton className="h-5 w-20 rounded-full bg-slate-200 dark:bg-slate-800" />
            <Skeleton className="h-7 w-3/4 rounded-full bg-slate-200 dark:bg-slate-800" />
          </div>
        </div>
        <div className="space-y-2">
          <Skeleton className="h-4 w-full bg-slate-200 dark:bg-slate-800" />
          <Skeleton className="h-4 w-[96%] bg-slate-200 dark:bg-slate-800" />
          <Skeleton className="h-4 w-[92%] bg-slate-200 dark:bg-slate-800" />
          <Skeleton className="h-4 w-[88%] bg-slate-200 dark:bg-slate-800" />
        </div>
        <div className="flex items-center justify-between border-t border-slate-200/80 pt-4 dark:border-slate-800">
          <Skeleton className="h-4 w-24 bg-slate-200 dark:bg-slate-800" />
          <Skeleton className="h-10 w-20 rounded-full bg-slate-200 dark:bg-slate-800" />
        </div>
      </div>
    </div>
  );
}

export default function IndustryTrendsInsightPage() {
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setIsLoading(false);
    }, 900);

    return () => window.clearTimeout(timer);
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-slate-100 px-4 py-10 text-slate-950 dark:from-slate-950 dark:via-slate-950 dark:to-slate-900 dark:text-white sm:px-6 lg:px-10 lg:py-14">
      <div className="mx-auto max-w-7xl">
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          className="mb-8 rounded-[2rem] border border-slate-200/80 bg-white/90 p-6 shadow-[0_18px_50px_rgba(15,23,42,0.05)] backdrop-blur dark:border-slate-800 dark:bg-slate-950/90 sm:p-8"
        >
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-3xl space-y-3">
              <div className="inline-flex w-fit items-center gap-2 rounded-full border border-emerald-900/10 bg-emerald-900/[0.05] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-950 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-200">
                <BarChart3 className="h-3.5 w-3.5" />
                Market Intelligence Dashboard
              </div>
              <h1 className="text-balance text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">
                Industry Trends Insight Cards
              </h1>
              <p className="max-w-2xl text-pretty text-sm leading-7 text-slate-600 dark:text-slate-300 sm:text-base">
                A consulting-style view of strategic themes, backed by recent
                examples and compact source attribution designed for executive
                briefings and research workflows.
              </p>
            </div>

            <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading curated signals
                </>
              ) : (
                <>
                  <span className="h-2.5 w-2.5 rounded-full bg-emerald-700 dark:bg-emerald-400" />
                  {trendData.length} trends ready
                </>
              )}
            </div>
          </div>
        </motion.section>

        <section className="grid gap-5 lg:grid-cols-2 xl:grid-cols-3">
          {isLoading
            ? Array.from({ length: 3 }).map((_, index) => (
                <TrendCardSkeleton key={index} />
              ))
            : trendData.map((trend, index) => (
                <TrendCard
                  key={trend.id}
                  trend={trend}
                  defaultExpanded={index === 0}
                />
              ))}
        </section>
      </div>
    </main>
  );
}
