"use client";

import { ExternalLink, FileText } from "lucide-react";

import { ScrollArea } from "./ui/scroll-area";

import type { Trend } from "./types";

type TrendSourcesProps = {
  sources: Trend["sources"];
};

export function TrendSources({ sources }: TrendSourcesProps) {
  return (
    <div className="rounded-[1.4rem] border border-slate-200/90 bg-slate-50/80 dark:border-slate-800 dark:bg-slate-950/50">
      <ScrollArea className="max-h-[22rem]">
        <div className="space-y-3 p-3 sm:p-4">
          {sources.map((source) => (
            <article
              key={source.id}
              className="rounded-2xl border border-slate-200/90 bg-white px-4 py-3 shadow-[0_8px_20px_rgba(15,23,42,0.03)] dark:border-slate-800 dark:bg-slate-950"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 dark:text-slate-400">
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                      <FileText className="h-3.5 w-3.5" />
                      Source {source.id}
                    </span>
                    {source.publication ? <span>{source.publication}</span> : null}
                    {source.year ? <span>{source.year}</span> : null}
                  </div>
                  <p className="text-sm font-medium leading-6 text-slate-800 dark:text-slate-100">
                    {source.title}
                  </p>
                </div>
                {source.url ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition-colors duration-200 hover:border-emerald-900/20 hover:text-emerald-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-800 focus-visible:ring-offset-2 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-emerald-700/30 dark:hover:text-emerald-300 dark:focus-visible:ring-emerald-400 dark:focus-visible:ring-offset-slate-950"
                    aria-label={`Open source ${source.id} in a new tab`}
                  >
                    <ExternalLink className="h-4 w-4" />
                  </a>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </ScrollArea>
      <div className="sticky bottom-0 flex items-center justify-between gap-3 rounded-b-[1.4rem] border-t border-slate-200/90 bg-white/95 px-4 py-3 text-xs text-slate-500 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95 dark:text-slate-400">
        <span>{sources.length} cited sources</span>
        <span>Scroll for full source list</span>
      </div>
    </div>
  );
}
