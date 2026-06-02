import React, {
  startTransition,
  useDeferredValue,
  useEffect,
  useRef,
  useState,
} from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import { createPortal, flushSync } from "https://esm.sh/react-dom@18.3.1";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "https://esm.sh/framer-motion@11.15.0?deps=react@18.3.1,react-dom@18.3.1";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);
const DEFAULT_API_CANDIDATES = [
  "https://osint-tool-backend.onrender.com",
  "https://osint-tool-for-alchemy-research-analyst-focused.onrender.com",
  "https://osint-tool-for-alchemy-research-analyst.onrender.com",
];
const API_URL =
  typeof window !== "undefined" && typeof window.OSINT_API_URL === "string" && window.OSINT_API_URL.trim()
    ? window.OSINT_API_URL.trim().replace(/\/+$/, "")
    : (
        typeof window !== "undefined" &&
        window.location &&
        window.location.hostname !== "127.0.0.1" &&
        window.location.hostname !== "localhost"
          ? window.location.origin.replace(/\/+$/, "")
          : DEFAULT_API_CANDIDATES[0]
      );
const STATIC_ASSET_VERSION =
  typeof window !== "undefined" && typeof window.__STATIC_ASSET_VERSION__ === "string"
    ? window.__STATIC_ASSET_VERSION__
    : "";

function apiUrl(path) {
  const normalizedPath = String(path || "");
  if (!normalizedPath) {
    return API_URL;
  }
  return `${API_URL}${normalizedPath.startsWith("/") ? normalizedPath : `/${normalizedPath}`}`;
}

function withStaticAssetVersion(path) {
  if (!STATIC_ASSET_VERSION) {
    return path;
  }

  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}v=${encodeURIComponent(STATIC_ASSET_VERSION)}`;
}

const DEFAULT_LOCATIONS = {
  preferences: [
    { value: "global", label: "Global" },
    { value: "region_specific", label: "Region Specific" },
    { value: "country_specific", label: "Country Specific" },
  ],
  regions: ["Asia", "Europe", "North America", "South America", "Africa", "Oceania"],
  countries: [],
};
const LOCATION_CACHE_KEY = "osint-location-catalog-v1";
const BUILT_IN_LOCATION_CATALOG_PATHS = [
  "../location-catalog.json",
  "/location-catalog.json",
  "/frontend/location-catalog.json",
];

const SECTION_OPTIONS = [
  { value: "trends", label: "Trends" },
  { value: "drivers", label: "Drivers" },
  { value: "competitive_landscape", label: "Competitive Landscape (CL)" },
];

const REGION_NOTES = {
  Asia: "Industrial, consumer, and policy shifts across high-growth economies.",
  Europe: "Regulatory movement, energy transitions, and mature-market indicators.",
  "North America": "Enterprise, capital, regulatory, and supply-chain signals.",
  "South America": "Commodity, infrastructure, consumer, and regional expansion themes.",
  Africa: "Mobile-first growth, infrastructure, and emerging market adoption patterns.",
  Oceania: "Trade, resources, public policy, and innovation ecosystem signals.",
};

const LIVE_JOURNAL = [
  "Interpreting your research brief...",
  "Drafting parallel search angles...",
  "Scanning for high-signal sources...",
  "Checking geographic fit and domain quality...",
  "Distilling notes into structured evidence...",
  "Preparing the final briefing canvas...",
];

const TRANSITION = { duration: 0.22, ease: [0.22, 1, 0.36, 1] };
const COMMAND_INPUT_CLASS = "command-control command-control--input";
const COMMAND_SELECT_CLASS = "command-control command-control--select command-select__trigger";
const MOTION_SMOOTH_STYLE = { willChange: "transform, opacity" };
const MOTION_EXPAND_STYLE = { willChange: "transform, opacity" };
const MOTION_SCALE_X_STYLE = {
  willChange: "transform",
  transformOrigin: "0% 50%",
};

function cx(...values) {
  return values.filter(Boolean).join(" ");
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function getFloatingLayerRoot() {
  if (typeof document === "undefined") {
    return null;
  }

  let root = document.getElementById("ui-floating-layer");
  if (!root) {
    root = document.createElement("div");
    root.id = "ui-floating-layer";
    root.className = "ui-floating-layer";
    document.body.appendChild(root);
  }
  return root;
}

function formatDuration(value) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return "0 ms";
  }
  if (numeric >= 1000) {
    return `${(numeric / 1000).toFixed(1)} s`;
  }
  return `${Math.round(numeric)} ms`;
}

function formatDate(value = new Date()) {
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(value);
}

function slugifyFilenamePart(value, fallback = "brief") {
  const normalized = String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || fallback;
}

function formatPreparedDateForFile(value = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(value);
}

function sectionTitle(section) {
  if (section === "drivers") {
    return "Market Drivers";
  }
  if (section === "competitive_landscape") {
    return "Competitive Landscape";
  }
  return "Industry Trends";
}

function sectionDescriptor(section) {
  if (section === "drivers") {
    return "Underlying forces accelerating or shaping the market.";
  }
  if (section === "competitive_landscape") {
    return "Key players mapped by relative market position, with concise company overviews and recent developments from the last 12 months.";
  }
  return "Observable patterns, shifts, and momentum lines across the landscape.";
}

function humanizePreference(preference) {
  if (preference === "country_specific") {
    return "Country";
  }
  if (preference === "region_specific") {
    return "Region";
  }
  return "Global";
}

function formatScopeSummary(meta) {
  const locationLabel = meta?.location?.label || "Global";
  return locationLabel;
}

function followUpSectionTitle(query, fallbackSection) {
  const normalized = String(query || "").trim();
  if (!normalized) {
    if (fallbackSection === "drivers") {
      return "Follow-up Drivers";
    }
    if (fallbackSection === "competitive_landscape") {
      return "Follow-up Competitive Landscape";
    }
    return "Follow-up Trends";
  }

  const lowered = normalized.toLowerCase();
  if (lowered.includes("m&a")) {
    return "M&A-Specific Trends";
  }
  if (lowered.includes("pricing")) {
    return "Pricing Shift Signals";
  }
  if (lowered.includes("merger") || lowered.includes("acquisition")) {
    return "Deals and Consolidation Signals";
  }

  return normalized
    .split(/\s+/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function truncate(value, maxLength = 88) {
  const normalized = String(value || "").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1)}...`;
}

function extractDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url || "source";
  }
}

function normalizeSourceList(rawSources) {
  if (!Array.isArray(rawSources)) {
    return [];
  }

  const normalizedSources = [];
  const seenKeys = new Set();

  rawSources.forEach((source, index) => {
    if (!source || typeof source !== "object") {
      return;
    }

    const normalizedSource = {
      source_id: String(source.source_id || source.id || index + 1).trim(),
      title: String(source.title || source.name || source.label || "").trim(),
      url: String(source.url || source.link || source.href || "").trim(),
      domain: String(source.domain || source.publisher || source.site || "").trim(),
      date: String(source.date || source.published_at || source.publishedDate || "").trim(),
      image_url: String(source.image_url || source.image || source.thumbnail || "").trim(),
    };

    if (!normalizedSource.title && !normalizedSource.url) {
      return;
    }

    const dedupeKey = `${normalizedSource.source_id}::${normalizedSource.title}::${normalizedSource.url}`;
    if (seenKeys.has(dedupeKey)) {
      return;
    }
    seenKeys.add(dedupeKey);
    normalizedSources.push(normalizedSource);
  });

  return normalizedSources;
}

function normalizeResearchItem(item) {
  if (!item || typeof item !== "object") {
    return null;
  }

  const heading = String(
    item.heading || item.title || item.name || item.label || item.main_trend || item.main_driver || "",
  ).trim();
  const body = String(
    item.body || item.description || item.details || item.summary || item.explanation || "",
  ).trim();
  if (!heading || !body) {
    return null;
  }

  const examples = Array.isArray(item.examples)
    ? item.examples
        .map((example) => {
          if (!example || typeof example !== "object") {
            return null;
          }
          const text = String(
            example.text || example.description || example.body || example.example || "",
          ).trim();
          const year = String(example.year || example.date || "").trim();
          if (!text) {
            return null;
          }
          return { text, year };
        })
        .filter(Boolean)
    : [];

  return {
    heading,
    body,
    segment: String(item.segment || item.player_segment || item.tier || item.bucket || "").trim().toLowerCase(),
    key_company_facts: Array.isArray(item.key_company_facts || item.key_facts || item.company_facts)
      ? (item.key_company_facts || item.key_facts || item.company_facts)
          .map((fact) => String(fact || "").trim())
          .filter((fact, index, facts) => fact && facts.indexOf(fact) === index)
          .slice(0, 5)
      : [],
    competitive_positioning: String(
      item.competitive_positioning || item.competitive_implication || item.positioning_implication || "",
    ).trim(),
    examples,
    sources: normalizeSourceList(item.sources || item.references || item.evidence),
    source_ids: Array.isArray(item.source_ids)
      ? item.source_ids
          .map((sourceId) => Number.parseInt(sourceId, 10))
          .filter((sourceId, index, values) => Number.isInteger(sourceId) && sourceId > 0 && values.indexOf(sourceId) === index)
      : [],
  };
}

function buildExistingChunks(result, debug) {
  const debugChunks = Array.isArray(debug?.cleaned_chunks)
    ? debug.cleaned_chunks
    : Array.isArray(debug?.existing_chunks)
      ? debug.existing_chunks
      : [];

  if (debugChunks.length) {
    return debugChunks
      .map((chunk, index) => ({
        text: String(chunk?.text || "").trim(),
        source_id: String(chunk?.source_id || `doc_${index + 1}`).trim(),
        source_title: String(chunk?.source_title || chunk?.title || `Source ${index + 1}`).trim(),
        source_url: String(chunk?.source_url || chunk?.url || "").trim(),
        source_domain: String(chunk?.source_domain || chunk?.domain || "").trim(),
        source_date: String(chunk?.source_date || chunk?.date || "").trim(),
      }))
      .filter((chunk) => chunk.text);
  }

  const items = Array.isArray(result?.items) ? result.items : [];
  return items.flatMap((item, index) => {
    const text = `${String(item?.heading || "").trim()}. ${String(item?.body || "").trim()}`.trim();
    const sources = Array.isArray(item?.sources) && item.sources.length
      ? item.sources
      : [{ source_id: `memo_${index + 1}`, title: `Memo ${index + 1}`, url: "", domain: "", date: "" }];

    return sources.map((source, sourceIndex) => ({
      text,
      source_id: String(source?.source_id || `memo_${index + 1}_${sourceIndex + 1}`).trim(),
      source_title: String(source?.title || `Memo ${index + 1}`).trim(),
      source_url: String(source?.url || "").trim(),
      source_domain: String(source?.domain || "").trim(),
      source_date: String(source?.date || "").trim(),
    }));
  });
}

function extractResearchItems(payload) {
  const normalizedPayload = normalizeResearchResponse(payload);
  return normalizedPayload ? normalizedPayload.items : [];
}

function buildLocationPayload(preference, value) {
  return {
    location_preference: preference,
    location_value: preference === "global" ? null : value || null,
  };
}

function deriveLocationMeta(preference, value, countries) {
  if (preference === "country_specific") {
    const selectedCountry = countries.find((country) => country.name === value);
    return {
      preference,
      scope: "country",
      label: value || "Country not selected",
      value: value || "",
      region: selectedCountry ? selectedCountry.region : "",
      strict: true,
    };
  }

  if (preference === "region_specific") {
    return {
      preference,
      scope: "region",
      label: value || "Region not selected",
      value: value || "",
      region: value || "",
      strict: false,
    };
  }

  return {
    preference: "global",
    scope: "global",
    label: "Global",
    value: "",
    region: "",
    strict: false,
  };
}

function normalizeResearchResponse(payload, fallbackSection = "trends") {
  if (!payload || typeof payload !== "object") {
    return null;
  }

  const inferredSection =
    payload.section === "trends" || payload.section === "drivers" || payload.section === "competitive_landscape"
      ? payload.section
      : Array.isArray(payload.drivers)
        ? "drivers"
        : Array.isArray(payload.competitive_landscape)
          ? "competitive_landscape"
        : Array.isArray(payload.trends)
          ? "trends"
          : fallbackSection;
  const rawItems = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload[inferredSection])
      ? payload[inferredSection]
      : [];
  const normalizedItems = rawItems.map(normalizeResearchItem).filter(Boolean);
  const title = String(payload.title || payload.heading || sectionTitle(inferredSection)).trim() || sectionTitle(inferredSection);

  return {
    ...payload,
    section: inferredSection,
    title,
    items: normalizedItems,
  };
}

function buildDownloadFileName(result, meta) {
  const scope = slugifyFilenamePart(meta?.location?.label || "global", "global");
  const topic = slugifyFilenamePart(meta?.topic || result?.title || "industry-brief", "industry-brief");
  const section = slugifyFilenamePart(result?.section || "trends", "trends");
  return `${topic}-${section}-${scope}-${formatPreparedDateForFile()}.html`;
}

async function triggerResultsDownload(result, meta, followUps = []) {
  if (typeof window === "undefined" || typeof document === "undefined" || !result) {
    return;
  }

  const completedFollowUps = Array.isArray(followUps)
    ? followUps
        .filter((entry) => entry?.status === "completed")
        .map((entry) => ({
          title: entry?.title,
          section: entry?.section || result?.section,
          items: Array.isArray(entry?.results)
            ? entry.results
            : Array.isArray(entry?.result?.items)
              ? entry.result.items
              : [],
          meta: entry?.meta || meta,
        }))
    : [];
  const payload = {
    result,
    meta: {
      ...meta,
      prepared: formatDate(),
    },
    follow_ups: completedFollowUps,
  };

  const response = await fetch(apiUrl("/api/export-memo"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = "Memo export failed.";
    try {
      const errorPayload = await response.json();
      if (errorPayload?.detail) {
        detail = String(errorPayload.detail);
      }
    } catch {
      // Ignore JSON parse failures for error responses.
    }
    throw new Error(detail);
  }

  const blob = await response.blob();
  if (!blob || blob.size === 0) {
    throw new Error("Memo export returned an empty file.");
  }

  const objectUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = buildDownloadFileName(result, meta);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => window.URL.revokeObjectURL(objectUrl), 1000);
}

function isResearchResponse(payload) {
  return Boolean(normalizeResearchResponse(payload));
}

function getLatestAnalysisContext(baseResult, baseDebug, followUps) {
  const completedFollowUps = Array.isArray(followUps)
    ? followUps.filter((entry) => entry?.status === "completed")
    : [];
  const latestFollowUp = completedFollowUps[completedFollowUps.length - 1];

  if (latestFollowUp?.result) {
    return {
      result: latestFollowUp.result,
      debug: latestFollowUp.debug || null,
      meta: latestFollowUp.meta || null,
    };
  }

  return {
    result: baseResult,
    debug: baseDebug,
    meta: null,
  };
}

function isLocationCatalog(payload) {
  return (
    payload &&
    typeof payload === "object" &&
    Array.isArray(payload.regions) &&
    Array.isArray(payload.countries)
  );
}

function normalizeLocationCatalog(payload) {
  if (!isLocationCatalog(payload)) {
    return null;
  }

  const normalizedCountries = Array.isArray(payload.countries) ? payload.countries : [];
  if (!normalizedCountries.length) {
    return null;
  }

  return {
    preferences:
      Array.isArray(payload.preferences) && payload.preferences.length
        ? payload.preferences
        : DEFAULT_LOCATIONS.preferences,
    regions: Array.isArray(payload.regions) ? payload.regions : DEFAULT_LOCATIONS.regions,
    countries: normalizedCountries,
  };
}

function loadCachedLocationCatalog() {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(LOCATION_CACHE_KEY);
    if (!raw) {
      return null;
    }
    return normalizeLocationCatalog(JSON.parse(raw));
  } catch {
    return null;
  }
}

function persistLocationCatalog(catalog) {
  if (typeof window === "undefined") {
    return;
  }

  try {
    window.localStorage.setItem(LOCATION_CACHE_KEY, JSON.stringify(catalog));
  } catch {
    // Ignore localStorage write failures and keep the in-memory catalog.
  }
}

async function loadBuiltInLocationCatalog() {
  for (const path of BUILT_IN_LOCATION_CATALOG_PATHS) {
    try {
      const response = await fetch(withStaticAssetVersion(path), {
        cache: "no-store",
      });
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      const normalizedCatalog = normalizeLocationCatalog(payload);
      if (!response.ok || !normalizedCatalog) {
        continue;
      }
      return normalizedCatalog;
    } catch {
      continue;
    }
  }
  return null;
}

function buildErrorMessage(payload, fallbackMessage) {
  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
    if (typeof payload.error === "string" && payload.error.trim()) {
      return payload.error;
    }
  }
  return fallbackMessage;
}

function buildCompletedJournal(result, debug, meta) {
  const queries = Array.isArray(debug?.queries) ? debug.queries : [];
  const selectedUrls = Array.isArray(debug?.selected_urls) ? debug.selected_urls : [];
  const sourceCount = Number(debug?.num_sources || selectedUrls.length || 0);
  const artifacts = debug?.artifact_counts || {};

  return [
    {
      id: "journal-scope",
      message: `Scoped the run to ${meta?.location?.label || "Global"} and prepared ${queries.length || 15} search angles.`,
    },
    {
      id: "journal-sources",
      message: `Promoted ${sourceCount || "multiple"} sources into the research set after quality and relevance checks.`,
    },
    {
      id: "journal-artifacts",
      message: `Captured ${artifacts.usable_text_count || 0} usable artifact extracts for synthesis.`,
    },
    {
      id: "journal-output",
      message: `Delivered ${result?.items?.length || 0} memo-ready ${result?.section === "drivers" ? "drivers" : result?.section === "competitive_landscape" ? "company profiles" : "insights"} in the final canvas.`,
    },
  ];
}

function PanelShell({ children, className = "" }) {
  return html`
    <section className=${cx("atelier-panel page-noise rounded-[30px]", className)}>
      ${children}
    </section>
  `;
}

function LaunchButton({ disabled = false, processing = false }) {
  return html`
    <button
      className="btn-17 command-deck-launch"
      type="submit"
      disabled=${disabled}
      aria-busy=${disabled ? "true" : "false"}
    >
      <span className="text-container">
        <span className="text">${processing ? "Processing..." : "Launch Analysis"}</span>
      </span>
    </button>
  `;
}

function SelectChevron({ open = false }) {
  return html`
    <svg
      className=${cx("command-select__chevron", open && "command-select__chevron--open")}
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M5.5 7.5L10 12l4.5-4.5"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  `;
}

function ThemedSelect({
  id,
  options,
  value,
  onChange,
  triggerClassName = COMMAND_SELECT_CLASS,
  disabled = false,
}) {
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState(null);
  const selectedOption = options.find((option) => option.value === value) || options[0] || null;
  const listboxId = `${id}-listbox`;

  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  useEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return undefined;
    }

    function syncMenuPosition() {
      if (!triggerRef.current || typeof window === "undefined") {
        return;
      }

      const rect = triggerRef.current.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const estimatedHeight = menuRef.current?.offsetHeight || Math.min(options.length * 58 + 18, 320);
      const spaceBelow = window.innerHeight - rect.bottom - viewportPadding;
      const spaceAbove = rect.top - viewportPadding;
      const placeAbove = spaceBelow < Math.min(estimatedHeight, 320) && spaceAbove > spaceBelow;
      const maxHeight = Math.max(
        150,
        Math.min(320, (placeAbove ? spaceAbove : spaceBelow) - gap),
      );
      const renderedHeight = Math.min(estimatedHeight, maxHeight);
      const width = Math.min(
        Math.max(rect.width, 220),
        Math.max(220, window.innerWidth - viewportPadding * 2),
      );
      const left = clamp(
        rect.left,
        viewportPadding,
        Math.max(viewportPadding, window.innerWidth - width - viewportPadding),
      );
      const top = placeAbove
        ? Math.max(viewportPadding, rect.top - renderedHeight - gap)
        : Math.max(viewportPadding, rect.bottom + gap);

      setMenuPosition({
        left,
        top,
        width,
        maxHeight,
      });
    }

    syncMenuPosition();
    const rafId = window.requestAnimationFrame(syncMenuPosition);
    window.addEventListener("resize", syncMenuPosition);
    window.addEventListener("scroll", syncMenuPosition, true);

    return () => {
      window.cancelAnimationFrame(rafId);
      window.removeEventListener("resize", syncMenuPosition);
      window.removeEventListener("scroll", syncMenuPosition, true);
    };
  }, [open, options.length]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    function handlePointerDown(event) {
      const target = event.target;
      const insideTrigger = rootRef.current && rootRef.current.contains(target);
      const insideMenu = menuRef.current && menuRef.current.contains(target);
      if (!insideTrigger && !insideMenu) {
        setOpen(false);
      }
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function toggleOpen() {
    if (disabled) {
      return;
    }
    setOpen((current) => !current);
  }

  function handleTriggerKeyDown(event) {
    if (disabled) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
    }
  }

  function handleSelect(nextValue) {
    if (nextValue !== value) {
      onChange(nextValue);
    }
    setOpen(false);
  }

  return html`
    <div
      className=${cx("command-select", open && "command-select--open")}
      ref=${rootRef}
    >
      <button
        id=${id}
        ref=${triggerRef}
        type="button"
        className=${triggerClassName}
        aria-expanded=${open ? "true" : "false"}
        aria-haspopup="listbox"
        aria-controls=${listboxId}
        disabled=${disabled}
        onClick=${toggleOpen}
        onKeyDown=${handleTriggerKeyDown}
      >
        <span className="command-select__value">${selectedOption ? selectedOption.label : ""}</span>
        <${SelectChevron} open=${open} />
      </button>

      ${open && menuPosition && getFloatingLayerRoot()
        ? createPortal(
            html`
              <${motion.div}
                key=${`${id}-menu`}
                id=${listboxId}
                ref=${menuRef}
                role="listbox"
                aria-labelledby=${id}
                initial=${{ opacity: 0, y: 8, scale: 0.98 }}
                animate=${{ opacity: 1, y: 0, scale: 1 }}
                transition=${{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                style=${{
                  ...MOTION_SMOOTH_STYLE,
                  top: `${menuPosition.top}px`,
                  left: `${menuPosition.left}px`,
                  width: `${menuPosition.width}px`,
                }}
                className="command-select__menu"
              >
                <div
                  className="command-select__menu-shell"
                  style=${{ maxHeight: `${menuPosition.maxHeight}px` }}
                >
                  ${options.map(
                    (option) => html`
                      <button
                        key=${option.value}
                        type="button"
                        role="option"
                        aria-selected=${option.value === value ? "true" : "false"}
                        className=${cx(
                          "command-select__option",
                          option.value === value && "command-select__option--selected",
                        )}
                        onClick=${() => handleSelect(option.value)}
                      >
                        <span className="command-select__option-label">${option.label}</span>
                        <span
                          className=${cx(
                            "command-select__option-mark",
                            option.value === value && "command-select__option-mark--selected",
                          )}
                          aria-hidden="true"
                        ></span>
                      </button>
                    `,
                  )}
                </div>
              </${motion.div}>
            `,
            getFloatingLayerRoot(),
          )
        : null}
    </div>
  `;
}

function CloseIcon() {
  return html`
    <svg
      className="filter-close-icon"
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M6 6l8 8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path
        d="M14 6l-8 8"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  `;
}

function EditFilterButton({ label, onClick, disabled = false }) {
  return html`
    <button
      type="button"
      disabled=${disabled}
      onClick=${onClick}
      className="edit-filter-button"
      aria-label=${label}
      title=${label}
    >
      <span className="edit-filter-button__label">${label}</span>
      <svg className="edit-filter-button__icon" viewBox="0 0 512 512" fill="none" aria-hidden="true">
        <path d="M410.3 231l11.3-11.3-33.9-33.9-62.1-62.1L291.7 89.8l-11.3 11.3-22.6 22.6L58.6 322.9c-10.4 10.4-18 23.3-22.2 37.4L1 480.7c-2.5 8.4-.2 17.5 6.1 23.7s15.3 8.5 23.7 6.1l120.3-35.4c14.1-4.2 27-11.8 37.4-22.2L387.7 253.7 410.3 231zM160 399.4l-9.1 22.7c-4 3.1-8.5 5.4-13.3 6.9L59.4 452l23-78.1c1.4-4.9 3.8-9.4 6.9-13.3l22.7-9.1v32c0 8.8 7.2 16 16 16h32zM362.7 18.7L348.3 33.2 325.7 55.8 314.3 67.1l33.9 33.9 62.1 62.1 33.9 33.9 11.3-11.3 22.6-22.6 14.5-14.5c25-25 25-65.5 0-90.5L453.3 18.7c-25-25-65.5-25-90.5 0zm-47.4 168l-144 144c-6.2 6.2-16.4 6.2-22.6 0s-6.2-16.4 0-22.6l144-144c6.2-6.2 16.4-6.2 22.6 0s6.2 16.4 0 22.6z" />
      </svg>
    </button>
  `;
}

function PanelHeader({ eyebrow, title, subtitle, action }) {
  return html`
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.28em] text-atelier-moss/70">
          ${eyebrow}
        </p>
        <h2 className="m-0 font-display text-[1.65rem] font-semibold leading-none text-atelier-ink">
          ${title}
        </h2>
        ${subtitle
          ? html`<p className="mt-2 max-w-2xl text-sm leading-6 text-atelier-moss">${subtitle}</p>`
          : null}
      </div>
      ${action || null}
    </div>
  `;
}

function DownloadResultsButton({ onClick, disabled = false, exporting = false }) {
  return html`
    <button
      type="button"
      className=${cx("download-results-button", exporting && "is-exporting")}
      onClick=${onClick}
      disabled=${disabled}
      aria-label=${exporting ? "Preparing memo download" : "Download memo HTML"}
      title=${exporting ? "Preparing memo download" : "Download memo HTML"}
    >
      <span className="download-results-button__icon-shell" aria-hidden="true">
        ${exporting
          ? html`<span className="download-results-button__spinner"></span>`
          : html`
              <svg
                className="download-results-button__icon"
                xmlns="http://www.w3.org/2000/svg"
                height="16"
                width="20"
                viewBox="0 0 640 512"
              >
                <path
                  d="M144 480C64.5 480 0 415.5 0 336c0-62.8 40.2-116.2 96.2-135.9c-.1-2.7-.2-5.4-.2-8.1c0-88.4 71.6-160 160-160c59.3 0 111 32.2 138.7 80.2C409.9 102 428.3 96 448 96c53 0 96 43 96 96c0 12.2-2.3 23.8-6.4 34.6C596 238.4 640 290.1 640 352c0 70.7-57.3 128-128 128H144zm79-167l80 80c9.4 9.4 24.6 9.4 33.9 0l80-80c9.4-9.4 9.4-24.6 0-33.9s-24.6-9.4-33.9 0l-39 39V184c0-13.3-10.7-24-24-24s-24 10.7-24 24V318.1l-39-39c-9.4-9.4-24.6-9.4-33.9 0s-9.4 24.6 0 33.9z"
                ></path>
              </svg>
            `}
      </span>
      <span className="download-results-button__copy">
        <span className="download-results-button__eyebrow">${exporting ? "Building HTML" : "Memo Export"}</span>
        <span className="download-results-button__label">${exporting ? "Preparing HTML..." : "Export HTML"}</span>
      </span>
    </button>
  `;
}

function WorkspaceHeader({ currentLocation }) {
  return html`
    <header className="relative z-10">
      <${PanelShell} className="overflow-hidden px-5 py-4 md:px-6">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div>
            <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.22em] text-atelier-moss/72">
              Analyst Workspace | ${formatDate()}
            </p>
            <h1 className="text-gradient m-0 font-display text-[2.9rem] font-semibold leading-[1.5] tracking-[-0.03em] md:text-[3.2rem]">
              The Intelligence & Insight Engine
            </h1>
            <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.24em] text-atelier-moss/78">
              Powered by Alchemy Research & Analytics
            </p>
            <p className="mt-2 max-w-3xl text-sm leading-7 text-atelier-moss">
              A polished OSINT research platform enabling unified discovery, verifiable evidence, and insight-ready outputs.
            </p>
          </div>

          <div className="xl:justify-self-end xl:text-right">
            <div>
              <p className="m-0 text-[11px] font-semibold uppercase tracking-[0.22em] text-atelier-moss/72">
                ${humanizePreference(currentLocation.preference)} Scope
              </p>
              <p className="mt-2 text-sm font-semibold text-atelier-ink">
                ${currentLocation.label || "Global"}
              </p>
            </div>
          </div>
        </div>
      </${PanelShell}>
    </header>
  `;
}

function RegionSelector({
  regions,
  searchValue,
  selectedValue,
  onSearchChange,
  onSelect,
  disabled = false,
}) {
  return html`
    <div className=${cx("grid gap-4 lg:grid-cols-[minmax(0,0.34fr)_minmax(0,0.66fr)]", disabled && "ui-disabled-shell")}>
      <div className="space-y-3">
        <label className="text-[11px] font-bold uppercase tracking-[0.26em] text-atelier-moss/72" for="regionSearch">
          Search Region
        </label>
        <input
          id="regionSearch"
          className="soft-inset w-full rounded-[22px] border border-atelier-line bg-white/75 px-4 py-3 text-sm text-atelier-ink placeholder:text-atelier-moss/45 focus:border-atelier-forest/28 focus:outline-none focus:ring-0"
          type="text"
          value=${searchValue}
          disabled=${disabled}
          onInput=${(event) => onSearchChange(event.currentTarget.value)}
          placeholder="Type Asia, Europe, Africa..."
        />
        <p className="text-sm leading-7 text-atelier-moss">
          Region mode gently biases query phrasing, ranking, and page filtering toward a continental market context.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        ${regions.length
          ? regions.map(
              (region) => html`
                <button
                  key=${region}
                  type="button"
                  disabled=${disabled}
                  onClick=${() => onSelect(region)}
                  className=${cx(
                    "lift-on-hover rounded-[24px] border px-4 py-4 text-left",
                    selectedValue === region
                      ? "bg-atelier-sage/10 border-atelier-sage/28 text-atelier-ink shadow-[0_14px_30px_rgba(39,67,60,0.08)]"
                      : "bg-white/72 border-atelier-line text-atelier-moss",
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="m-0 text-sm font-bold text-atelier-ink">${region}</p>
                      <p className="mt-2 text-xs leading-6 text-atelier-moss">
                        ${REGION_NOTES[region] || "Regional context and market-specific signals."}
                      </p>
                    </div>
                    ${selectedValue === region
                      ? html`<span className="rounded-full bg-atelier-sage/14 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-atelier-forest">Selected</span>`
                      : null}
                  </div>
                </button>
              `,
            )
          : html`
              <div className="rounded-[24px] border border-dashed border-atelier-line bg-white/64 px-4 py-5 text-sm text-atelier-moss">
                No regions match that search.
              </div>
            `}
      </div>
    </div>
  `;
}

function CountrySelector({
  countries,
  allCountriesCount = 0,
  searchValue,
  selectedValue,
  onSearchChange,
  onSelect,
  disabled = false,
}) {
  return html`
    <div className=${cx("grid gap-4 lg:grid-cols-[minmax(0,0.34fr)_minmax(0,0.66fr)]", disabled && "ui-disabled-shell")}>
      <div className="space-y-3">
        <label className="text-[11px] font-bold uppercase tracking-[0.26em] text-atelier-moss/72" for="countrySearch">
          Country Typeahead
        </label>
        <input
          id="countrySearch"
          className="soft-inset w-full rounded-[22px] border border-atelier-line bg-white/75 px-4 py-3 text-sm text-atelier-ink placeholder:text-atelier-moss/45 focus:border-atelier-forest/28 focus:outline-none focus:ring-0"
          type="text"
          value=${searchValue}
          disabled=${disabled}
          onInput=${(event) => onSearchChange(event.currentTarget.value)}
          placeholder="Search countries like India, Germany, Brazil..."
        />
        <p className="text-sm leading-7 text-atelier-moss">
          Country mode is strict. Pages that do not clearly reflect the selected country are removed from the final source set.
        </p>
      </div>

      <div className="atelier-panel-strong rounded-[24px] p-2">
        <div className="panel-scroll max-h-[16rem] space-y-2 pr-1">
          ${countries.length
            ? countries.map(
                (country) => html`
                  <button
                    key=${country.name}
                    type="button"
                    disabled=${disabled}
                    onClick=${() => onSelect(country.name)}
                    className=${cx(
                      "lift-on-hover flex w-full items-center justify-between gap-4 rounded-[20px] border px-4 py-3 text-left",
                      selectedValue === country.name
                        ? "bg-atelier-sage/10 border-atelier-sage/26 text-atelier-ink"
                        : "bg-white/70 border-atelier-line text-atelier-moss",
                    )}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-bold text-atelier-ink">${country.name}</span>
                      <span className="mt-1 block text-[11px] uppercase tracking-[0.18em] text-atelier-moss/72">
                        ${country.region}
                      </span>
                    </span>
                    ${selectedValue === country.name
                      ? html`<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-forest">Selected</span>`
                      : null}
                  </button>
                `,
              )
            : html`
                <div className="rounded-[22px] border border-dashed border-atelier-line bg-white/70 px-4 py-5 text-sm text-atelier-moss">
                  ${allCountriesCount
                    ? "No countries match that search."
                    : "Countries are temporarily unavailable. The last location refresh did not return a usable country list."}
                </div>
              `}
        </div>
      </div>
    </div>
  `;
}

function CommandDeck({
  topic,
  section,
  locationPreference,
  locationValue,
  secondaryFilterOpen,
  locations,
  analysisError,
  locationLoadError,
  isProcessing,
  regionQuery,
  countryQuery,
  filteredRegions,
  filteredCountries,
  allCountriesCount,
  onTopicChange,
  onSectionChange,
  onPreferenceChange,
  onRegionQueryChange,
  onCountryQueryChange,
  onLocationSelect,
  onOpenSecondaryFilter,
  onCloseSecondaryFilter,
  onAnalyze,
}) {
  const scopedFilterActive = locationPreference !== "global";
  const showSecondaryFilterPanel = scopedFilterActive && (secondaryFilterOpen || !locationValue);
  const selectedScopeLabel =
    locationPreference === "country_specific" ? "Country" : "Region";

  return html`
    <${motion.div}
      initial=${{ opacity: 0, y: 18 }}
      animate=${{ opacity: 1, y: 0 }}
      transition=${TRANSITION}
      style=${MOTION_SMOOTH_STYLE}
      className="min-h-0"
    >
      <${PanelShell} className="atelier-panel-crisp overflow-hidden px-5 py-5 md:px-6 md:py-6">
        <${PanelHeader}
          eyebrow="Command Deck"
          title="Design the research run"
          subtitle="Set the topic, choose the section, apply the geographic lens, and launch a run that stays traceable from first query to final memo."
        />

        <form className="mt-6 grid gap-4" onSubmit=${onAnalyze}>
          <div className=${cx("atelier-panel-strong rounded-[26px] px-4 py-4", isProcessing && "ui-disabled-shell")}>
            <div className="command-deck-grid grid gap-4 xl:grid-cols-[minmax(0,2.4fr)_minmax(12.75rem,0.9fr)_minmax(14.25rem,1fr)_minmax(14.5rem,0.8fr)]">
              <div className="command-deck-field">
                <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="topicInput">
                  Topic Input
                </label>
                <input
                  id="topicInput"
                  className=${COMMAND_INPUT_CLASS}
                  type="text"
                  value=${topic}
                  disabled=${isProcessing}
                  onInput=${(event) => onTopicChange(event.currentTarget.value)}
                  placeholder="EV adoption, critical minerals, mobile gaming in India, supply chain shifts..."
                />
              </div>

              <div className="command-deck-field">
                <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="sectionSelect">
                  Section
                </label>
                <${ThemedSelect}
                  id="sectionSelect"
                  options=${SECTION_OPTIONS}
                  value=${section}
                  onChange=${onSectionChange}
                  disabled=${isProcessing}
                />
              </div>

              <div className="command-deck-field">
                <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="locationPreference">
                  Location Preference
                </label>
                <${ThemedSelect}
                  id="locationPreference"
                  options=${locations.preferences}
                  value=${locationPreference}
                  onChange=${onPreferenceChange}
                  disabled=${isProcessing}
                />
              </div>

              <div className="command-deck-action">
                <${LaunchButton} disabled=${isProcessing} processing=${isProcessing} />
              </div>
            </div>

            <p className="mt-2 text-xs leading-6 text-atelier-moss">
              Keep the topic natural. The platform will expand it into query angles, vet sources, and turn the strongest evidence into a structured brief.
            </p>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <div className="atelier-panel-strong rounded-[24px] px-4 py-4">
              <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="sectionSelect">
                Briefing Lens
              </label>
              <p className="m-0 text-sm font-bold text-atelier-ink">${sectionTitle(section)}</p>
              <p className="mt-2 text-xs leading-5 text-atelier-moss">${sectionDescriptor(section)}</p>
            </div>

            <div className="atelier-panel-strong rounded-[24px] px-4 py-4">
              <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
                Geographic Behavior
              </label>
              <p className="m-0 text-sm font-bold text-atelier-ink">
                ${locationPreference === "global" ? "Global" : humanizePreference(locationPreference)}
              </p>
              <p className="mt-2 text-xs leading-5 text-atelier-moss">
                Global keeps the run wide; regional adds gentle relevance; country applies strict filtering.
              </p>
              ${locationValue
                ? html`
                    <p className="mt-3 text-sm font-semibold text-atelier-ink">
                      ${selectedScopeLabel}: ${locationValue}
                    </p>
                  `
                : null}
              ${scopedFilterActive && !showSecondaryFilterPanel && locationValue
                ? html`
                    <div className="mt-3">
                      <${EditFilterButton}
                        label=${`Edit ${selectedScopeLabel} Filter`}
                        disabled=${isProcessing}
                        onClick=${onOpenSecondaryFilter}
                      />
                    </div>
                  `
                : null}
            </div>
          </div>

          <${AnimatePresence} initial=${false} mode="wait">
            ${locationPreference === "region_specific" && showSecondaryFilterPanel
              ? html`
                  <${motion.div}
                    key="region-selector"
                    initial=${{ opacity: 0, y: 10, scale: 0.985 }}
                    animate=${{ opacity: 1, y: 0, scale: 1 }}
                    exit=${{ opacity: 0, y: -8, scale: 0.985 }}
                    transition=${TRANSITION}
                    style=${MOTION_EXPAND_STYLE}
                    className="overflow-hidden origin-top"
                  >
                    <div className="atelier-panel-strong rounded-[28px] px-4 py-4">
                      <div className="mb-4 flex items-center justify-between gap-4">
                        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
                          Secondary Filter Panel
                        </p>
                        ${locationValue
                          ? html`
                              <button
                                type="button"
                                disabled=${isProcessing}
                                onClick=${onCloseSecondaryFilter}
                                aria-label="Close secondary filter panel"
                                className="filter-close-button"
                              >
                                <${CloseIcon} />
                              </button>
                            `
                          : null}
                      </div>
                      <${RegionSelector}
                        regions=${filteredRegions}
                        searchValue=${regionQuery}
                        selectedValue=${locationValue}
                        disabled=${isProcessing}
                        onSearchChange=${onRegionQueryChange}
                        onSelect=${onLocationSelect}
                      />
                    </div>
                  </${motion.div}>
                `
              : null}

            ${locationPreference === "country_specific" && showSecondaryFilterPanel
              ? html`
                  <${motion.div}
                    key="country-selector"
                    initial=${{ opacity: 0, y: 10, scale: 0.985 }}
                    animate=${{ opacity: 1, y: 0, scale: 1 }}
                    exit=${{ opacity: 0, y: -8, scale: 0.985 }}
                    transition=${TRANSITION}
                    style=${MOTION_EXPAND_STYLE}
                    className="overflow-hidden origin-top"
                  >
                    <div className="atelier-panel-strong rounded-[28px] px-4 py-4">
                      <div className="mb-4 flex items-center justify-between gap-4">
                        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
                          Secondary Filter Panel
                        </p>
                        ${locationValue
                          ? html`
                              <button
                                type="button"
                                disabled=${isProcessing}
                                onClick=${onCloseSecondaryFilter}
                                aria-label="Close secondary filter panel"
                                className="filter-close-button"
                              >
                                <${CloseIcon} />
                              </button>
                            `
                          : null}
                      </div>
                      <${CountrySelector}
                        countries=${filteredCountries}
                        allCountriesCount=${allCountriesCount}
                        searchValue=${countryQuery}
                        selectedValue=${locationValue}
                        disabled=${isProcessing}
                        onSearchChange=${onCountryQueryChange}
                        onSelect=${onLocationSelect}
                      />
                    </div>
                  </${motion.div}>
                `
              : null}
          </${AnimatePresence}>

          ${analysisError
            ? html`
                <div className="rounded-[24px] border border-rose-200 bg-rose-50 px-4 py-4 text-sm leading-7 text-rose-700">
                  ${analysisError}
                </div>
              `
            : null}

          ${locationLoadError
            ? html`
                <div className="rounded-[24px] border border-amber-200 bg-amber-50 px-4 py-4 text-sm leading-7 text-amber-900">
                  ${locationLoadError}
                </div>
              `
            : null}
        </form>
      </${PanelShell}>
    </${motion.div}>
  `;
}

function JournalIdle({ meta }) {
  return html`
    <div className="atelier-panel-strong rounded-[26px] px-5 py-5">
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
        Idle State
      </p>
      <h3 className="mt-3 font-display text-[2rem] font-semibold leading-none text-atelier-ink">
        Set the brief, then launch the desk
      </h3>
      <p className="mt-3 text-sm leading-7 text-atelier-moss">
        This field-notes rail will track query expansion, source retrieval, filtering choices, and runtime details once analysis begins. Current scope: <span className="font-bold text-atelier-ink">${formatScopeSummary(meta)}</span>.
      </p>
    </div>
  `;
}

function JournalAnalyzing({ progressValue, liveJournal, reducedMotion }) {
  return html`
    <div className="atelier-panel-strong rounded-[26px] px-5 py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Analyzing
          </p>
          <h3 className="mt-3 font-display text-[1.95rem] font-semibold leading-none text-atelier-ink">
            Processing the research run
          </h3>
          <p className="mt-3 text-sm leading-7 text-atelier-moss">
            The workflow is moving from discovery to evidence curation to memo composition.
          </p>
        </div>
        <p className="m-0 text-sm font-semibold text-atelier-goldDeep">
          ${Math.max(8, Math.round(progressValue))}%
        </p>
      </div>

      <div className="mt-5 h-3 rounded-full bg-atelier-forest/8">
        <${motion.div}
          className="progress-ribbon h-full w-full rounded-full"
          initial=${{ scaleX: 0 }}
          animate=${{ scaleX: Math.max(10, progressValue) / 100 }}
          transition=${reducedMotion ? { duration: 0 } : { duration: 0.45, ease: "easeOut" }}
          style=${MOTION_SCALE_X_STYLE}
        />
      </div>

      <div className="editorial-rule mt-6"></div>

      <div className="mt-6">
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
          Live Notes
        </p>
        <div className="mt-4 space-y-3">
          ${liveJournal.map(
            (entry) => html`
              <div
                key=${entry.id}
                className="rounded-[20px] border border-atelier-line bg-white/74 px-4 py-3 text-sm leading-7 text-atelier-moss"
              >
                ${entry.message}
              </div>
            `,
          )}
        </div>
      </div>
    </div>
  `;
}

function MetricCard({ label, value, tone = "default" }) {
  const toneClass =
    tone === "accent"
      ? "metric-accent"
      : tone === "gold"
        ? "metric-gold"
        : "metric-card";

  return html`
    <div className=${cx("rounded-[22px] border px-4 py-4", toneClass)}>
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/68">${label}</p>
      <p className="mt-2 text-lg font-bold text-atelier-ink">${value}</p>
    </div>
  `;
}

function JournalCompleted({ result, debug, meta }) {
  const queries = Array.isArray(debug?.queries) ? debug.queries : [];
  const sourceScores = Array.isArray(debug?.source_scores) ? debug.source_scores : [];
  const executionTime = debug?.execution_time || {};
  const artifactCounts = debug?.artifact_counts || {};
  const queryPerformance = debug?.query_performance || {};

  return html`
    <div className="atelier-panel-strong rounded-[26px] px-5 py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Run Summary
          </p>
          <h3 className="mt-3 font-display text-[1.95rem] font-semibold leading-none text-atelier-ink">
            Analysis complete
          </h3>
          <p className="mt-3 text-sm leading-7 text-atelier-moss">
            The field notes below capture timing, search expansion, and source quality from the finished run.
          </p>
        </div>
        <p className="m-0 text-sm font-semibold text-atelier-goldDeep">
          ${formatDuration(executionTime.pipeline_ms)}
        </p>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <${MetricCard} label="Scope" value=${meta?.location?.label || "Global"} tone="accent" />
        <${MetricCard} label="Section" value=${sectionTitle(result?.section)} tone="gold" />
        <${MetricCard} label="Sources" value=${String(debug?.num_sources || 0)} />
        <${MetricCard} label="Pipeline" value=${formatDuration(executionTime.pipeline_ms)} />
      </div>

      <div className="editorial-rule mt-6"></div>

      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Search Angles
          </p>
          <p className="m-0 text-sm font-semibold text-atelier-ink">${queries.length} queries</p>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          ${queries.length
            ? queries.map(
                (query) => html`
                  <span
                    key=${query}
                    className="rounded-full border border-atelier-line bg-white/84 px-3 py-2 text-xs leading-6 text-atelier-moss"
                  >
                    ${query}
                  </span>
                `,
              )
            : html`<p className="m-0 text-sm leading-7 text-atelier-moss">No query metadata was returned for this run.</p>`}
        </div>
      </div>

      <div className="editorial-rule mt-6"></div>

      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Source Ledger
          </p>
          <p className="m-0 text-sm font-semibold text-atelier-ink">
            ${artifactCounts.usable_text_count || 0} usable
          </p>
        </div>
        <div className="mt-4 space-y-3">
          ${sourceScores.length
            ? sourceScores.slice(0, 6).map(
                (source) => html`
                  <div
                    key=${source.url}
                    className="rounded-[22px] border border-atelier-line bg-white/80 px-4 py-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="m-0 truncate text-sm font-bold text-atelier-ink">${extractDomain(source.url)}</p>
                        <p className="mt-2 text-xs uppercase tracking-[0.18em] text-atelier-moss/68">
                          Score ${source.score || 0}
                          ${source.location_score ? ` | Location ${source.location_score}` : ""}
                        </p>
                      </div>
                      ${source.years?.length
                        ? html`
                            <span className="rounded-full bg-atelier-forest/6 px-3 py-1 text-[11px] text-atelier-moss">
                              ${source.years.join(", ")}
                            </span>
                          `
                        : null}
                    </div>
                  </div>
                `,
              )
            : html`<p className="m-0 text-sm leading-7 text-atelier-moss">Source-level scoring metadata was not available.</p>`}
        </div>
      </div>

      <div className="editorial-rule mt-6"></div>

      <div className="mt-6">
        <div className="flex items-center justify-between gap-3">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Run Notes
          </p>
          <p className="m-0 text-sm font-semibold text-atelier-ink">
            ${Object.keys(queryPerformance).length} tracked searches
          </p>
        </div>
        <div className="mt-4 space-y-3">
          ${buildCompletedJournal(result, debug, meta).map(
            (entry) => html`
              <div
                key=${entry.id}
                className="rounded-[20px] border border-atelier-line bg-white/76 px-4 py-3 text-sm leading-7 text-atelier-moss"
              >
                ${entry.message}
              </div>
            `,
          )}
        </div>
      </div>
    </div>
  `;
}

function JournalError({ message }) {
  return html`
    <div className="rounded-[26px] border border-rose-200 bg-rose-50 px-5 py-5">
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-rose-700/86">
        Run Interrupted
      </p>
      <h3 className="mt-3 font-display text-[1.8rem] font-semibold leading-none text-rose-900">
        The desk needs one more pass
      </h3>
      <p className="mt-3 text-sm leading-7 text-rose-800">${message}</p>
      <p className="mt-4 text-sm leading-7 text-rose-800/85">
        Update the brief parameters and launch again to rebuild the source set and output.
      </p>
    </div>
  `;
}

function FieldNotesPane({
  analysisState,
  result,
  debug,
  meta,
  analysisError,
  liveJournal,
  progressValue,
  reducedMotion,
}) {
  return html`
    <${PanelShell} className="workspace-pane flex min-h-0 flex-col overflow-hidden px-5 py-5 md:px-6 md:py-6">
      <${PanelHeader}
        eyebrow="Field Notes"
        title="Evidence, workflow, and analyst memory"
        subtitle="This rail keeps the run honest: how the brief was shaped, where it looked, what it kept, and the timing behind the result."
      />

      <div className="workspace-pane-body mt-5 min-h-0 flex-1 overflow-hidden">
        <${AnimatePresence} initial=${false} mode="wait">
          ${analysisState === "completed"
            ? html`<${JournalCompleted} key="journal-completed" result=${result} debug=${debug} meta=${meta} />`
            : null}
          ${analysisState === "analyzing"
            ? html`
                <${JournalAnalyzing}
                  key="journal-analyzing"
                  progressValue=${progressValue}
                  liveJournal=${liveJournal}
                  reducedMotion=${reducedMotion}
                />
              `
            : null}
          ${analysisState === "error"
            ? html`<${JournalError} key="journal-error" message=${analysisError} />`
            : null}
          ${analysisState === "idle"
            ? html`<${JournalIdle} key="journal-idle" meta=${meta} />`
            : null}
        </${AnimatePresence}>
      </div>
    </${PanelShell}>
  `;
}

function BriefIdle({ meta }) {
  return html`
    <div className="flex min-h-[24rem] items-center justify-center">
      <div className="paper-sheet w-full max-w-3xl rounded-[30px] px-8 py-10 text-center">
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.26em] text-atelier-moss/68">
          Briefing Canvas
        </p>
        <h3 className="mt-5 font-display text-[2.7rem] font-semibold leading-none text-atelier-ink">
          Ready for the next intelligence brief
        </h3>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-8 text-atelier-moss">
          The final memo will appear here once the run completes. Current lens: <span className="font-bold text-atelier-ink">${formatScopeSummary(meta)}</span>.
        </p>
      </div>
    </div>
  `;
}

function PencilLoader({ onReady, frameId = 0 }) {
  return html`
    <iframe
      aria-hidden="true"
      className="pencil-loader-frame"
      key=${`pencil-loader-${frameId}`}
      loading="eager"
      onLoad=${onReady}
      scrolling="no"
      src=${withStaticAssetVersion("/ui/pencil-loader.html")}
      tabIndex="-1"
      title="Pencil loading animation"
    ></iframe>
  `;
}

function BriefAnalyzing({ progressValue, onLoaderReady, loaderFrameId }) {
  return html`
    <div className="flex min-h-[24rem] items-center justify-center">
      <div className="paper-sheet w-full max-w-3xl rounded-[30px] px-8 py-8">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
              Drafting Brief
            </p>
            <h3 className="mt-3 font-display text-[2.2rem] font-semibold leading-none text-atelier-ink">
              Writing the results canvas
            </h3>
          </div>
          <p className="m-0 text-sm font-semibold text-atelier-goldDeep">
            ${Math.max(8, Math.round(progressValue))}%
          </p>
        </div>
        <div className="editorial-rule"></div>
        <div className="mt-7 flex flex-col items-center justify-center text-center">
          <div className="pencil-loader-shell">
            <${PencilLoader} onReady=${onLoaderReady} frameId=${loaderFrameId} />
          </div>
          <p className="mt-4 max-w-xl text-sm leading-7 text-atelier-moss">
            The platform is turning validated evidence into a memo-ready brief. Queries, source checks, and synthesis are still in motion.
          </p>
        </div>
        <div className="mt-7 space-y-5">
          ${[0, 1, 2, 3].map(
            (index) => html`
              <div key=${index} className="rounded-[24px] border border-atelier-line bg-white/76 px-5 py-5">
                <div className="skeleton-wash h-3 w-16 rounded-full"></div>
                <div className="skeleton-wash mt-4 h-7 w-3/4 rounded-full"></div>
                <div className="skeleton-wash mt-4 h-3 w-full rounded-full"></div>
                <div className="skeleton-wash mt-3 h-3 w-[92%] rounded-full"></div>
                <div className="skeleton-wash mt-3 h-3 w-[80%] rounded-full"></div>
              </div>
            `,
          )}
        </div>
      </div>
    </div>
  `;
}

function WorkspaceTransitionShell() {
  return html`
    <${motion.div}
      initial=${{ opacity: 0 }}
      animate=${{ opacity: 1 }}
      exit=${{ opacity: 0 }}
      transition=${{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
      style=${MOTION_SMOOTH_STYLE}
      className="absolute inset-0 z-20 grid gap-4 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]"
    >
      <${PanelShell} className="workspace-pane pointer-events-none flex min-h-0 flex-col overflow-hidden px-5 py-5 md:px-6 md:py-6">
        <div className="atelier-panel-strong rounded-[26px] px-5 py-5">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Field Notes
          </p>
          <div className="skeleton-wash mt-4 h-10 w-3/4 rounded-full"></div>
          <div className="skeleton-wash mt-4 h-3 w-full rounded-full"></div>
          <div className="skeleton-wash mt-3 h-3 w-[88%] rounded-full"></div>
          <div className="mt-6 h-3 rounded-full bg-atelier-forest/8">
            <${motion.div}
              className="progress-ribbon h-full w-full rounded-full"
              initial=${{ scaleX: 0.18 }}
              animate=${{ scaleX: [0.18, 0.54, 0.32] }}
              transition=${{ duration: 1.2, repeat: Infinity, ease: "linear" }}
              style=${MOTION_SCALE_X_STYLE}
            />
          </div>
          <div className="mt-6 space-y-3">
            ${[0, 1, 2].map(
              (index) => html`
                <div key=${index} className="rounded-[22px] border border-atelier-line bg-white/74 px-4 py-4">
                  <div className="skeleton-wash h-3 w-24 rounded-full"></div>
                  <div className="skeleton-wash mt-4 h-3 w-full rounded-full"></div>
                  <div className="skeleton-wash mt-3 h-3 w-[84%] rounded-full"></div>
                </div>
              `,
            )}
          </div>
        </div>
      </${PanelShell}>

      <${PanelShell} className="workspace-pane pointer-events-none flex min-h-0 flex-col overflow-hidden px-5 py-5 md:px-6 md:py-6">
        <div className="paper-sheet flex min-h-[24rem] flex-col rounded-[30px] px-8 py-8">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="skeleton-wash h-3 w-28 rounded-full"></div>
              <div className="skeleton-wash mt-4 h-10 w-72 rounded-full"></div>
            </div>
            <div className="skeleton-wash h-9 w-20 rounded-full"></div>
          </div>
          <div className="editorial-rule mt-6"></div>
          <div className="mt-8 flex-1 space-y-5">
            ${[0, 1, 2, 3].map(
              (index) => html`
                <div key=${index} className="rounded-[24px] border border-atelier-line bg-white/76 px-5 py-5">
                  <div className="skeleton-wash h-3 w-16 rounded-full"></div>
                  <div className="skeleton-wash mt-4 h-7 w-3/4 rounded-full"></div>
                  <div className="skeleton-wash mt-4 h-3 w-full rounded-full"></div>
                  <div className="skeleton-wash mt-3 h-3 w-[92%] rounded-full"></div>
                  <div className="skeleton-wash mt-3 h-3 w-[80%] rounded-full"></div>
                </div>
              `,
            )}
          </div>
        </div>
      </${PanelShell}>
    </${motion.div}>
  `;
}

function BriefMetaRow({ meta, debug, section }) {
  const sourceCount = Number(debug?.num_sources || debug?.selected_urls?.length || 0);
  return html`
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <div>
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/66">Section</p>
        <p className="mt-2 text-sm font-bold text-atelier-ink">${sectionTitle(section)}</p>
      </div>
      <div>
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/66">Scope</p>
        <p className="mt-2 text-sm font-bold text-atelier-ink">${meta?.location?.label || "Global"}</p>
      </div>
      <div>
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/66">Sources</p>
        <p className="mt-2 text-sm font-bold text-atelier-ink">${sourceCount || "N/A"}</p>
      </div>
      <div>
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/66">Prepared</p>
        <p className="mt-2 text-sm font-bold text-atelier-ink">${formatDate()}</p>
      </div>
    </div>
  `;
}

function FollowUpTrigger({ open, onClick, disabled = false }) {
  return html`
    <button
      type="button"
      disabled=${disabled}
      onClick=${onClick}
      className="group inline-flex items-center gap-2 rounded-full border border-atelier-line bg-white/66 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.18em] text-atelier-moss opacity-72 transition-colors duration-200 hover:border-atelier-forest/22 hover:bg-white/92 hover:text-atelier-ink hover:opacity-100"
      aria-expanded=${open ? "true" : "false"}
      title="Ask a follow-up question"
    >
      <svg className="h-4 w-4 transition-transform duration-200 group-hover:scale-105" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M7 17.5h3.2l3.9 3.1c.4.3.9 0 .9-.5v-2.6h2.5A3.5 3.5 0 0 0 21 14V7.5A3.5 3.5 0 0 0 17.5 4h-11A3.5 3.5 0 0 0 3 7.5V14A3.5 3.5 0 0 0 6.5 17.5H7Z" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M8 9.5h8M8 12.5h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      <span>${open ? "Close" : "Follow-up"}</span>
    </button>
  `;
}

function FollowUpInput({
  isOpen,
  value,
  loading,
  disabled,
  onChange,
  onSubmit,
}) {
  return html`
    <${AnimatePresence} initial=${false}>
      ${isOpen
        ? html`
            <${motion.div}
              key="followup-input"
              initial=${{ opacity: 0, y: 10, scale: 0.99 }}
              animate=${{ opacity: 1, y: 0, scale: 1 }}
              exit=${{ opacity: 0, y: 6, scale: 0.99 }}
              transition=${TRANSITION}
              style=${MOTION_EXPAND_STYLE}
              className="overflow-hidden origin-top"
            >
              <form onSubmit=${onSubmit} className=${cx("rounded-[24px] border border-atelier-line bg-white/72 px-4 py-4", disabled && "ui-disabled-shell")}>
                <div className="flex flex-col gap-3 md:flex-row md:items-end">
                  <div className="min-w-0 flex-1">
                    <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68" for="followupQueryInput">
                      Follow-up Query
                    </label>
                    <textarea
                      id="followupQueryInput"
                      rows="2"
                      className="soft-inset min-h-[5.25rem] w-full rounded-[20px] border border-atelier-line bg-white/86 px-4 py-3 text-sm leading-7 text-atelier-ink placeholder:text-atelier-moss/45 focus:border-atelier-forest/28 focus:outline-none focus:ring-0"
                      placeholder="Ask a follow-up (e.g., M&A-specific trends, pricing shifts...)"
                      value=${value}
                      disabled=${disabled}
                      onInput=${(event) => onChange(event.currentTarget.value)}
                    ></textarea>
                  </div>
                  <button
                    type="submit"
                    disabled=${disabled || loading || !String(value || "").trim()}
                    className="inline-flex h-[3.25rem] items-center justify-center rounded-full bg-atelier-ink px-5 text-xs font-bold uppercase tracking-[0.2em] text-atelier-paper transition-colors duration-200 hover:bg-atelier-forest disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    ${loading ? "Processing..." : "Send"}
                  </button>
                </div>
              </form>
            </${motion.div}>
          `
        : null}
    </${AnimatePresence}>
  `;
}

function FollowUpConfirmationCard({
  refinedQuery,
  draftValue,
  loading,
  disabled,
  onDraftChange,
  onConfirm,
  onEdit,
}) {
  return html`
    <${motion.div}
      initial=${{ opacity: 0, y: 12 }}
      animate=${{ opacity: 1, y: 0 }}
      transition=${TRANSITION}
      style=${MOTION_SMOOTH_STYLE}
      className="rounded-[24px] border border-atelier-line bg-white/80 px-4 py-4"
    >
      <p className="m-0 text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
        Query Check
      </p>
      <p className="mt-3 text-sm font-semibold text-atelier-ink">
        Did you mean: <span className="text-atelier-forest">${refinedQuery}</span>?
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick=${onConfirm}
          disabled=${disabled || loading}
          className="inline-flex items-center justify-center rounded-full bg-atelier-ink px-4 py-2 text-[11px] font-bold uppercase tracking-[0.18em] text-atelier-paper transition-colors duration-300 hover:bg-atelier-forest disabled:opacity-45"
        >
          Yes
        </button>
        <button
          type="button"
          onClick=${onEdit}
          disabled=${disabled || loading}
          className="inline-flex items-center justify-center rounded-full border border-atelier-line bg-white/72 px-4 py-2 text-[11px] font-bold uppercase tracking-[0.18em] text-atelier-moss transition-colors duration-300 hover:text-atelier-ink disabled:opacity-45"
        >
          Edit
        </button>
      </div>
      <div className="mt-4">
        <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68" for="followupDraftInput">
          Refine Manually
        </label>
        <input
          id="followupDraftInput"
          className="soft-inset w-full rounded-[18px] border border-atelier-line bg-white/84 px-4 py-3 text-sm text-atelier-ink placeholder:text-atelier-moss/45 focus:border-atelier-forest/28 focus:outline-none focus:ring-0"
          type="text"
          value=${draftValue}
          disabled=${disabled}
          onInput=${(event) => onDraftChange(event.currentTarget.value)}
        />
      </div>
    </${motion.div}>
  `;
}

function FollowUpCard({ entry }) {
  const isLoading = entry.status === "loading";
  const expansionUsed = entry.decision === "PARTIAL" || entry.decision === "INSUFFICIENT";
  const tagLabel = expansionUsed ? "Expanded research" : "Used existing data";
  const tagTone = expansionUsed
    ? "bg-atelier-gold/12 text-atelier-goldDeep border-atelier-gold/20"
    : "bg-atelier-sage/12 text-atelier-forest border-atelier-sage/22";

  return html`
    <div className="rounded-[24px] border border-atelier-line bg-white/78 px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="m-0 text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/68">
            Follow-up Request
          </p>
          <p className="mt-2 text-sm font-semibold text-atelier-ink">${entry.query}</p>
          ${entry.refined_query
            ? html`<p className="mt-2 text-sm leading-7 text-atelier-moss">Refined to: ${entry.refined_query}</p>`
            : null}
        </div>
        ${entry.decision
          ? html`
              <div className="flex flex-wrap items-center gap-2">
                <span className=${cx("rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em]", tagTone)}>
                  ${tagLabel}
                </span>
                <span className="rounded-full border border-atelier-line bg-white/84 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss">
                  ${entry.decision}
                </span>
              </div>
            `
          : null}
      </div>

      ${isLoading
        ? html`
            <div className="mt-4 flex items-center gap-3 rounded-[18px] border border-atelier-line bg-white/76 px-4 py-3 text-sm text-atelier-moss">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-atelier-forest/20 border-t-atelier-forest"></span>
              <span>${entry.loading_message || "Analyzing existing research..."}</span>
            </div>
          `
        : null}

      ${entry.reason && !isLoading
        ? html`<p className="mt-4 text-sm leading-7 text-atelier-moss">${entry.reason}</p>`
        : null}
    </div>
  `;
}

function SourceList({ sources }) {
  const normalizedSources = Array.isArray(sources) ? sources.filter((source) => source?.title || source?.url) : [];

  if (!normalizedSources.length) {
    return null;
  }

  return html`
    <div className="space-y-3">
      ${normalizedSources.map(
        (source, index) => html`
          ${source.url
            ? html`<a
                key=${`${source.url || source.title}-${index}`}
                href=${source.url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-[18px] border border-atelier-line bg-white/84 px-4 py-3 no-underline transition-colors duration-200 hover:border-atelier-forest/24 hover:bg-white"
              >
                ${source.image_url
                  ? html`<div className="mb-3 overflow-hidden rounded-[14px] border border-atelier-line bg-atelier-paper/70">
                      <img
                        src=${source.image_url}
                        alt=${source.title || source.url || `Source ${index + 1}`}
                        loading="lazy"
                        referrerPolicy="no-referrer"
                        className="block h-40 w-full object-cover"
                      />
                    </div>`
                  : null}
                <p className="m-0 text-sm font-bold text-atelier-ink">
                  ${source.title || source.url || `Source ${index + 1}`}
                </p>
                <p className="mt-1 text-xs uppercase tracking-[0.18em] text-atelier-moss/75">
                  ${source.domain || extractDomain(source.url)}${source.date ? ` | ${source.date}` : ""}
                </p>
                <p className="mt-2 break-all text-xs leading-6 text-atelier-moss">
                  ${source.url}
                </p>
              </a>`
            : html`<div
                key=${`${source.title || "source"}-${index}`}
                className="block rounded-[18px] border border-atelier-line bg-white/84 px-4 py-3"
              >
                <p className="m-0 text-sm font-bold text-atelier-ink">
                  ${source.title || `Source ${index + 1}`}
                </p>
                <p className="mt-1 text-xs uppercase tracking-[0.18em] text-atelier-moss/75">
                  ${source.domain || "Source reference"}${source.date ? ` | ${source.date}` : ""}
                </p>
                <p className="mt-2 text-xs leading-6 text-atelier-moss">
                  Source URL unavailable
                </p>
              </div>`}
        `,
      )}
    </div>
  `;
}

function SourceDisclosure({ sources }) {
  const [open, setOpen] = useState(false);
  const normalizedSources = Array.isArray(sources) ? sources.filter((source) => source?.title || source?.url) : [];

  if (!normalizedSources.length) {
    return null;
  }

  return html`
    <div className="mt-7 rounded-[22px] border border-atelier-line bg-white/72">
      <button
        type="button"
        onClick=${() => setOpen((current) => !current)}
        aria-expanded=${open ? "true" : "false"}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
      >
        <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
          Sources (${normalizedSources.length})
        </span>
        <span className="text-xs font-bold uppercase tracking-[0.2em] text-atelier-forest">
          ${open ? "Hide" : "Show"}
        </span>
      </button>

      <${AnimatePresence} initial=${false}>
        ${open
          ? html`
              <${motion.div}
                key="competitive-sources-panel"
                initial=${{ opacity: 0, y: 8, scale: 0.99 }}
                animate=${{ opacity: 1, y: 0, scale: 1 }}
                exit=${{ opacity: 0, y: 6, scale: 0.99 }}
                transition=${TRANSITION}
                style=${MOTION_EXPAND_STYLE}
                className="overflow-hidden origin-top border-t border-atelier-line"
              >
                <div className="px-4 py-4">
                  <${SourceList} sources=${normalizedSources} />
                </div>
              </${motion.div}>
            `
          : null}
      </${AnimatePresence}>
    </div>
  `;
}

function ExamplesAndSourcesDisclosure({ examples, sources }) {
  const [open, setOpen] = useState(false);
  const normalizedExamples = Array.isArray(examples) ? examples.filter((example) => example?.text) : [];
  const normalizedSources = Array.isArray(sources) ? sources.filter((source) => source?.title || source?.url) : [];

  if (!normalizedSources.length && !normalizedExamples.length) {
    return null;
  }

  return html`
    <div className="mt-5 rounded-[22px] border border-atelier-line bg-white/72">
      <button
        type="button"
        onClick=${() => setOpen((current) => !current)}
        aria-expanded=${open ? "true" : "false"}
        className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
      >
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
            Sources (${normalizedSources.length})
          </span>
          <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss/70">
            Examples (${normalizedExamples.length})
          </span>
        </div>
        <span className="text-xs font-bold uppercase tracking-[0.2em] text-atelier-forest">
          ${open ? "Hide" : "Show"}
        </span>
      </button>

      <${AnimatePresence} initial=${false}>
        ${open
          ? html`
              <${motion.div}
                key="sources-panel"
                initial=${{ opacity: 0, y: 8, scale: 0.99 }}
                animate=${{ opacity: 1, y: 0, scale: 1 }}
                exit=${{ opacity: 0, y: 6, scale: 0.99 }}
                transition=${TRANSITION}
                style=${MOTION_EXPAND_STYLE}
                className="overflow-hidden origin-top border-t border-atelier-line"
              >
                <div className="space-y-3 px-4 py-4">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/70">
                        Recent Examples
                      </p>
                      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.18em] text-atelier-moss/55">
                        ${normalizedExamples.length ? `${normalizedExamples.length} available` : "Not generated"}
                      </p>
                    </div>
                    ${normalizedExamples.length
                      ? html`
                          <div className="space-y-3">
                            ${normalizedExamples.map(
                              (example, index) => html`
                                <div
                                  key=${`${example.text}-${index}`}
                                  className="rounded-[18px] border border-atelier-line bg-white/84 px-4 py-3"
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <p className="m-0 text-sm leading-7 text-atelier-ink">
                                      ${example.text}
                                    </p>
                                    ${example.year
                                      ? html`
                                          <span className="inline-flex flex-none items-center rounded-full border border-atelier-forest/12 bg-atelier-forest/[0.05] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-atelier-forest">
                                            ${example.year}
                                          </span>
                                        `
                                      : null}
                                  </div>
                                </div>
                              `,
                            )}
                          </div>
                        `
                      : html`
                          <div className="rounded-[18px] border border-dashed border-atelier-line bg-white/70 px-4 py-3">
                            <p className="m-0 text-sm leading-7 text-atelier-moss">
                              No explicit recent examples were generated for this insight from the current evidence set.
                            </p>
                          </div>
                        `}
                  </div>

                  ${normalizedSources.length
                    ? html`
                        <div className="space-y-3">
                          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/70">
                            Sources
                          </p>
                          <${SourceList} sources=${normalizedSources} />
                        </div>
                      `
                    : null}
                </div>
              </${motion.div}>
            `
          : null}
      </${AnimatePresence}>
    </div>
  `;
}

function CompetitiveLandscapeDevelopments({ examples = [] }) {
  const normalizedExamples = Array.isArray(examples) ? examples.filter((example) => example?.text) : [];
  if (!normalizedExamples.length) {
    return null;
  }

  return html`
    <section className="mt-6">
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
        Recent Strategic Developments
      </p>
      <ol className="mt-3 list-decimal space-y-3 pl-6 text-sm leading-7 text-atelier-moss">
        ${normalizedExamples.map(
          (example, index) => html`
            <li key=${`${example.text}-${index}`} className="pl-1">
              <span className="text-atelier-ink">${example.text}</span>
              ${example.year
                ? html`<span className="ml-2 text-xs font-bold uppercase tracking-[0.16em] text-atelier-goldDeep">
                    ${example.year}
                  </span>`
                : null}
            </li>
          `,
        )}
      </ol>
    </section>
  `;
}

function CompetitiveLandscapeFacts({ facts = [] }) {
  const normalizedFacts = Array.isArray(facts) ? facts.filter(Boolean) : [];
  if (!normalizedFacts.length) {
    return null;
  }

  return html`
    <section className="mt-6">
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
        Key Company Facts
      </p>
      <ul className="mt-3 space-y-3 pl-5 text-sm leading-7 text-atelier-moss">
        ${normalizedFacts.map(
          (fact, index) => html`
            <li key=${`${fact}-${index}`} className="pl-1 text-atelier-ink">
              ${fact}
            </li>
          `,
        )}
      </ul>
    </section>
  `;
}

function CompetitiveLandscapePositioning({ text = "" }) {
  const normalizedText = String(text || "").trim();
  if (!normalizedText) {
    return null;
  }

  return html`
    <section className="mt-6">
      <p className="m-0 text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
        Competitive Positioning / Implication
      </p>
      <p className="mt-3 text-sm leading-7 text-atelier-moss">
        ${normalizedText || "No clear competitive implication could be validated from the current evidence set."}
      </p>
    </section>
  `;
}

function BriefItemCard({ item, index, section, title }) {
  if (section === "competitive_landscape") {
    return html`
      <${motion.article}
        key=${`${title}-${item.heading}-${index}`}
        initial=${{ opacity: 0, y: 16 }}
        animate=${{ opacity: 1, y: 0 }}
        transition=${{ ...TRANSITION, delay: index * 0.05 }}
        style=${MOTION_SMOOTH_STYLE}
        className="rounded-[26px] border border-atelier-line bg-white/78 px-5 py-5"
      >
        <div className="flex items-start gap-4">
          <div className="brief-item-index flex h-11 w-11 flex-none items-center justify-center rounded-full text-sm font-bold">
            ${index + 1}
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="mt-2 font-display text-[2rem] font-semibold leading-[1.02] text-atelier-ink">
              ${item.heading}
            </h4>
            <section className="mt-6">
              <p className="m-0 text-[11px] font-bold uppercase tracking-[0.2em] text-atelier-moss">
                Business Overview
              </p>
              <p className="mt-3 text-sm leading-8 text-atelier-moss">
                ${item.body}
              </p>
            </section>
            <${CompetitiveLandscapeFacts} facts=${item.key_company_facts} />
            <${CompetitiveLandscapeDevelopments} examples=${item.examples} />
            <${CompetitiveLandscapePositioning} text=${item.competitive_positioning} />
            <${SourceDisclosure} sources=${item.sources} />
          </div>
        </div>
      </${motion.article}>
    `;
  }

  return html`
    <${motion.article}
      key=${`${title}-${item.heading}-${index}`}
      initial=${{ opacity: 0, y: 16 }}
      animate=${{ opacity: 1, y: 0 }}
      transition=${{ ...TRANSITION, delay: index * 0.05 }}
      style=${MOTION_SMOOTH_STYLE}
      className="rounded-[26px] border border-atelier-line bg-white/78 px-5 py-5"
    >
      <div className="flex items-start gap-4">
        <div className="brief-item-index flex h-11 w-11 flex-none items-center justify-center rounded-full text-sm font-bold">
          ${index + 1}
        </div>
        <div className="min-w-0 flex-1">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/66">
            ${section === "drivers" ? "Driver" : "Trend"}
          </p>
          <h4 className="mt-3 font-display text-[2rem] font-semibold leading-[1.02] text-atelier-ink">
            ${item.heading}
          </h4>
          <p className="mt-4 text-sm leading-8 text-atelier-moss">
            ${item.body}
          </p>
          <${ExamplesAndSourcesDisclosure} examples=${item.examples} sources=${item.sources} />
        </div>
      </div>
    </${motion.article}>
  `;
}

function ResultSection({
  title,
  section,
  items,
  meta,
  debug,
  compact = false,
  aside = null,
}) {
  const normalizedItems = Array.isArray(items) ? items : [];
  return html`
    <div className=${cx("paper-sheet flex w-full flex-col rounded-[30px]", compact ? "px-5 py-5 md:px-6" : "px-6 py-6 md:px-8")}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.26em] text-atelier-moss/68">
            ${compact ? "Follow-up Brief" : "Final Brief"}
          </p>
          <h3 className=${cx("mt-3 font-display font-semibold text-atelier-ink", compact ? "text-[2.2rem] leading-[1]" : "text-[3rem] leading-[0.92]")}>
            ${title}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          ${aside || null}
          <p className="m-0 text-sm font-semibold text-atelier-ink">
            ${formatScopeSummary(meta)} | ${sectionTitle(section)}
          </p>
        </div>
      </div>

      <p className="mt-4 max-w-3xl text-sm leading-8 text-atelier-moss">
        ${meta?.topic || "Research topic"}. ${sectionDescriptor(section)}
      </p>

      <div className="mt-5 rounded-[24px] border border-atelier-line bg-white/72 px-5 py-4">
        <${BriefMetaRow} meta=${meta} debug=${debug} section=${section} />
      </div>

      <div className="editorial-rule mt-6"></div>

      <div className="mt-6 space-y-4">
        ${normalizedItems.length
          ? normalizedItems.map(
              (item, index) => html`
                <${BriefItemCard}
                  item=${item}
                  index=${index}
                  section=${section}
                  title=${title}
                />
              `,
            )
          : html`
              <div className="rounded-[26px] border border-dashed border-atelier-line bg-white/76 px-5 py-6 text-sm leading-8 text-atelier-moss">
                No strong insights found.
              </div>
            `}
      </div>
    </div>
  `;
}

function BriefCompleted({
  result,
  debug,
  meta,
  onDownload,
  exportPending,
  followUpOpen,
  followUpQuery,
  followUpDraft,
  followUpPending,
  followUps,
  isProcessing,
  onToggleFollowUp,
  onFollowUpQueryChange,
  onFollowUpDraftChange,
  onFollowUpSubmit,
  onFollowUpConfirm,
  onFollowUpEdit,
}) {
  return html`
    <div className="flex justify-center">
      <div className="flex w-full max-w-4xl flex-col gap-5">
        <${ResultSection}
          title=${result.title || sectionTitle(result.section)}
          section=${result.section}
          items=${result.items}
          meta=${meta}
          debug=${debug}
          aside=${html`<${DownloadResultsButton} onClick=${onDownload} exporting=${exportPending} disabled=${exportPending} />`}
        />

        <div className="flex items-center justify-start">
          <${FollowUpTrigger} open=${followUpOpen} onClick=${onToggleFollowUp} disabled=${isProcessing} />
        </div>

        <${FollowUpInput}
          isOpen=${followUpOpen}
          value=${followUpQuery}
          loading=${isProcessing}
          disabled=${isProcessing}
          onChange=${onFollowUpQueryChange}
          onSubmit=${onFollowUpSubmit}
        />

        ${followUpPending?.status === "confirming"
          ? html`
              <${FollowUpConfirmationCard}
                refinedQuery=${followUpPending.refined_query}
                draftValue=${followUpDraft}
                loading=${false}
                disabled=${isProcessing}
                onDraftChange=${onFollowUpDraftChange}
                onConfirm=${onFollowUpConfirm}
                onEdit=${onFollowUpEdit}
              />
            `
          : null}

        ${followUpPending?.status === "loading"
          ? html`<${FollowUpCard} entry=${followUpPending} />`
          : null}

        ${followUps.length
          ? html`
              <div className="space-y-5">
                ${followUps.map(
                  (entry, index) => html`
                    <div key=${entry.id || `${entry.query}-${index}`} className="space-y-4">
                      <${FollowUpCard} entry=${entry} />
                      <${ResultSection}
                        title=${entry.title}
                        section=${entry.section || result.section}
                        items=${entry.results}
                        meta=${entry.meta || meta}
                        debug=${entry.debug || debug}
                        compact=${true}
                      />
                    </div>
                  `,
                )}
              </div>
            `
          : null}
      </div>
    </div>
  `;
}

function BriefError({ message }) {
  return html`
    <div className="flex min-h-[24rem] items-center justify-center">
      <div className="paper-sheet w-full max-w-3xl rounded-[30px] px-8 py-10 text-center">
        <p className="m-0 text-[11px] font-bold uppercase tracking-[0.26em] text-rose-700/76">
          Brief Unavailable
        </p>
        <h3 className="mt-5 font-display text-[2.5rem] font-semibold leading-none text-atelier-ink">
          The memo could not be prepared cleanly
        </h3>
        <p className="mx-auto mt-4 max-w-2xl text-sm leading-8 text-rose-800">
          ${message}
        </p>
      </div>
    </div>
  `;
}

function BriefingCanvas({
  analysisState,
  result,
  debug,
  meta,
  analysisError,
  progressValue,
  onLoaderReady,
  loaderFrameId,
  onDownload,
  exportPending,
  followUpOpen,
  followUpQuery,
  followUpDraft,
  followUpPending,
  followUps,
  isProcessing,
  onToggleFollowUp,
  onFollowUpQueryChange,
  onFollowUpDraftChange,
  onFollowUpSubmit,
  onFollowUpConfirm,
  onFollowUpEdit,
}) {
  return html`
    <${PanelShell} className="workspace-pane flex min-h-0 flex-col overflow-hidden px-5 py-5 md:px-6 md:py-6">
      <${PanelHeader}
        eyebrow="Briefing Canvas"
        title="Structured output, designed like a finished memo"
        subtitle="The right pane stays focused on the deliverable: a polished brief with context, scope, and clear reading rhythm."
      />

      <div className="workspace-pane-body mt-5 min-h-0 flex-1 overflow-hidden">
        <${AnimatePresence} initial=${false} mode="wait">
          ${analysisState === "completed"
            ? html`
                <${BriefCompleted}
                  key="brief-completed"
                  result=${result}
                  debug=${debug}
                  meta=${meta}
                  onDownload=${onDownload}
                  exportPending=${exportPending}
                  followUpOpen=${followUpOpen}
                  followUpQuery=${followUpQuery}
                  followUpDraft=${followUpDraft}
                  followUpPending=${followUpPending}
                  followUps=${followUps}
                  isProcessing=${isProcessing}
                  onToggleFollowUp=${onToggleFollowUp}
                  onFollowUpQueryChange=${onFollowUpQueryChange}
                  onFollowUpDraftChange=${onFollowUpDraftChange}
                  onFollowUpSubmit=${onFollowUpSubmit}
                  onFollowUpConfirm=${onFollowUpConfirm}
                  onFollowUpEdit=${onFollowUpEdit}
                />
              `
            : null}
          ${analysisState === "analyzing"
            ? html`
                <${BriefAnalyzing}
                  key="brief-analyzing"
                  progressValue=${progressValue}
                  onLoaderReady=${onLoaderReady}
                  loaderFrameId=${loaderFrameId}
                />
              `
            : null}
          ${analysisState === "error"
            ? html`<${BriefError} key="brief-error" message=${analysisError} />`
            : null}
          ${analysisState === "idle"
            ? html`<${BriefIdle} key="brief-idle" meta=${meta} />`
            : null}
        </${AnimatePresence}>
      </div>
    </${PanelShell}>
  `;
}

function App() {
  const reducedMotion = useReducedMotion();
  const [isProcessing, setIsProcessing] = useState(false);
  const [topic, setTopic] = useState("");
  const [section, setSection] = useState("trends");
  const [locationPreference, setLocationPreference] = useState("global");
  const [locationValue, setLocationValue] = useState("");
  const [locations, setLocations] = useState(() => loadCachedLocationCatalog() || DEFAULT_LOCATIONS);
  const [locationLoadError, setLocationLoadError] = useState("");
  const [regionQuery, setRegionQuery] = useState("");
  const [countryQuery, setCountryQuery] = useState("");
  const [analysisState, setAnalysisState] = useState("idle");
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisDebug, setAnalysisDebug] = useState(null);
  const [analysisMeta, setAnalysisMeta] = useState({
    topic: "",
    location: deriveLocationMeta("global", "", []),
  });
  const [analysisError, setAnalysisError] = useState("");
  const [liveJournal, setLiveJournal] = useState([]);
  const [progressValue, setProgressValue] = useState(0);
  const [secondaryFilterOpen, setSecondaryFilterOpen] = useState(false);
  const [workspaceSurfaceState, setWorkspaceSurfaceState] = useState("hidden");
  const [loaderFrameId, setLoaderFrameId] = useState(0);
  const [followUpOpen, setFollowUpOpen] = useState(false);
  const [followUpQuery, setFollowUpQuery] = useState("");
  const [followUpDraft, setFollowUpDraft] = useState("");
  const [followUpPending, setFollowUpPending] = useState(null);
  const [followUps, setFollowUps] = useState([]);
  const [exportPending, setExportPending] = useState(false);
  const journalSeedRef = useRef(0);
  const deferredRegionQuery = useDeferredValue(regionQuery);
  const deferredCountryQuery = useDeferredValue(countryQuery);

  async function handleDownloadResults() {
    if (!analysisResult) {
      return;
    }
    setExportPending(true);
    try {
      await triggerResultsDownload(analysisResult, analysisMeta, followUps);
    } catch (error) {
      console.error("Memo export failed", error);
      window.alert("Memo export failed. Please try again.");
    } finally {
      setExportPending(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function loadLocations() {
      try {
        const response = await fetch(apiUrl("/api/locations"));
        let payload = null;
        try {
          payload = await response.json();
        } catch {
          payload = null;
        }

        const normalizedCatalog = normalizeLocationCatalog(payload);
        if (!response.ok || !normalizedCatalog) {
          throw new Error("The location catalogue could not be loaded.");
        }

        if (!cancelled) {
          persistLocationCatalog(normalizedCatalog);
          startTransition(() => {
            setLocations(normalizedCatalog);
            setLocationLoadError("");
          });
        }
      } catch {
        if (!cancelled) {
          const cachedLocations = loadCachedLocationCatalog();
          const builtInLocations = await loadBuiltInLocationCatalog();
          const nextLocations =
            cachedLocations ||
            builtInLocations ||
            (Array.isArray(locations?.countries) && locations.countries.length ? locations : null) ||
            DEFAULT_LOCATIONS;

          if (builtInLocations) {
            persistLocationCatalog(builtInLocations);
          }

          setLocationLoadError(
            cachedLocations
              ? "The live location catalogue could not be refreshed, so the last saved location list is being used."
              : builtInLocations
                ? "The live location catalogue could not be refreshed, so the built-in location list is being used."
                : "The live location catalogue could not be refreshed, and no usable built-in country list was found.",
          );
          setLocations(nextLocations);
        }
      }
    }

    loadLocations();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Warm the exact iframe assets so the loader appears immediately on first run.
    fetch(withStaticAssetVersion("/ui/pencil-loader.css"), { cache: "force-cache" }).catch(() => {});
    fetch(withStaticAssetVersion("/ui/pencil-loader.html"), { cache: "force-cache" }).catch(() => {});
  }, []);

  useEffect(() => {
    setLocationValue("");
    setRegionQuery("");
    setCountryQuery("");
    setSecondaryFilterOpen(locationPreference !== "global");
  }, [locationPreference]);

  useEffect(() => {
    if (analysisState !== "analyzing") {
      return undefined;
    }

    setProgressValue(12);
    journalSeedRef.current += 1;
    setLiveJournal([
      {
        id: `journal-${Date.now()}-${journalSeedRef.current}`,
        message: LIVE_JOURNAL[0],
      },
    ]);

    let progress = 12;
    let messageIndex = 1;
    const interval = window.setInterval(() => {
      progress = Math.min(progress + 13, 90);
      setProgressValue((current) => Math.max(current, progress));
      journalSeedRef.current += 1;
      setLiveJournal((previous) =>
        [
          ...previous,
          {
            id: `journal-${Date.now()}-${journalSeedRef.current}`,
            message: LIVE_JOURNAL[messageIndex % LIVE_JOURNAL.length],
          },
        ].slice(-6),
      );
      messageIndex += 1;
    }, reducedMotion ? 1500 : 900);

    return () => {
      window.clearInterval(interval);
    };
  }, [analysisState, reducedMotion]);

  useEffect(() => {
    if (analysisState === "idle") {
      setWorkspaceSurfaceState("hidden");
      return;
    }

    if (analysisState === "completed" || analysisState === "error") {
      setWorkspaceSurfaceState("visible");
    }
  }, [analysisState]);

  const currentLocationMeta = deriveLocationMeta(
    locationPreference,
    locationValue,
    locations.countries,
  );
  const filteredRegions = locations.regions.filter((region) =>
    !deferredRegionQuery.trim() ||
    region.toLowerCase().includes(deferredRegionQuery.trim().toLowerCase()),
  );

  const filteredCountries = locations.countries.filter((country) => {
    const query = deferredCountryQuery.trim().toLowerCase();
    if (!query) {
      return true;
    }
    return `${country.name} ${country.region}`.toLowerCase().includes(query);
  });
  const allCountriesCount = Array.isArray(locations.countries) ? locations.countries.length : 0;

  const displayMeta =
    analysisState === "completed"
      ? analysisMeta
      : {
          topic: topic.trim(),
          location: currentLocationMeta,
        };

  const showWorkspacePanels =
    analysisState !== "idle" || workspaceSurfaceState !== "hidden";
  const isWorkspaceTransitioning = workspaceSurfaceState === "transitioning";

  function handleBriefingLoaderReady() {
    setWorkspaceSurfaceState((current) =>
      current === "transitioning" ? "visible" : current,
    );
  }

  function resetFollowUps() {
    setFollowUpOpen(false);
    setFollowUpQuery("");
    setFollowUpDraft("");
    setFollowUpPending(null);
    setFollowUps([]);
  }

  function toggleFollowUpComposer() {
    if (isProcessing) {
      return;
    }
    setFollowUpOpen((current) => !current);
    setFollowUpPending(null);
  }

  async function requestFollowUpDecision(queryText) {
    const trimmedQuery = String(queryText || "").trim();
    if (!trimmedQuery || !analysisResult || isProcessing) {
      return;
    }

    const latestContext = getLatestAnalysisContext(analysisResult, analysisDebug, followUps);
    const existingChunks = buildExistingChunks(latestContext.result, latestContext.debug);
    const metadataPayload = {
      topic: latestContext.meta?.topic || analysisMeta?.topic || topic.trim(),
      section: latestContext.result?.section || analysisResult?.section || section,
      location: latestContext.meta?.location?.label || analysisMeta?.location?.label || "",
      location_preference: latestContext.meta?.location?.preference || analysisMeta?.location?.preference || locationPreference,
      location_value: latestContext.meta?.location?.value || analysisMeta?.location?.value || locationValue,
    };

    const loadingId = `followup-loading-${Date.now()}`;
    const loadingMessage =
      existingChunks.length >= 2 ? "Analyzing existing research..." : "Expanding research...";

    setFollowUpPending({
      id: loadingId,
      status: "loading",
      query: trimmedQuery,
      refined_query: trimmedQuery,
      loading_message: loadingMessage,
    });
    setIsProcessing(true);

    try {
      const response = await fetch(apiUrl("/api/follow-up"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          follow_up_query: trimmedQuery,
          existing_chunks: existingChunks,
          metadata: metadataPayload,
        }),
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      if (!response.ok) {
        throw new Error(buildErrorMessage(payload, "Follow-up request failed. Please try again."));
      }

      const refinedQuery = String(payload?.refined_query || trimmedQuery).trim() || trimmedQuery;
      setFollowUpDraft(refinedQuery);
      setFollowUpPending({
        id: loadingId,
        status: "confirming",
        query: trimmedQuery,
        refined_query: refinedQuery,
        payload,
      });
    } catch (error) {
      const refinedQuery = trimmedQuery;
      const payload = {
        decision: "PARTIAL",
        refined_query: refinedQuery,
        reason:
          error instanceof Error
            ? error.message
            : "Follow-up request failed. Please try again.",
        new_queries: [],
      };
      setFollowUpDraft(refinedQuery);
      setFollowUpPending({
        id: loadingId,
        status: "confirming",
        query: trimmedQuery,
        refined_query: refinedQuery,
        payload,
      });
    } finally {
      setIsProcessing(false);
    }
  }

  async function finalizeFollowUp() {
    if (!followUpPending?.payload || isProcessing) {
      return;
    }

    const finalRefinedQuery = String(followUpDraft || followUpPending.refined_query || "").trim();
    const payload = {
      ...followUpPending.payload,
      refined_query: finalRefinedQuery || followUpPending.refined_query,
    };
    const latestContext = getLatestAnalysisContext(analysisResult, analysisDebug, followUps);
    const existingChunks = buildExistingChunks(latestContext.result, latestContext.debug);
    const resultSection = latestContext.result?.section || analysisResult?.section || section;
    const decision = payload?.decision || "PARTIAL";
    const loadingMessage =
      decision === "SUFFICIENT"
        ? "Analyzing existing research..."
        : "Expanding research with new sources...";

    setFollowUpPending((current) =>
      current
        ? {
            ...current,
            status: "loading",
            refined_query: payload.refined_query,
            loading_message: loadingMessage,
          }
        : current,
    );
    setIsProcessing(true);

    try {
      let response = null;
      if (decision === "SUFFICIENT") {
        response = await fetch(apiUrl("/api/analyze-existing"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            refined_query: payload.refined_query,
            existing_chunks: existingChunks,
            metadata: {
              topic: latestContext.meta?.topic || analysisMeta?.topic || topic.trim(),
              section: resultSection,
              location_preference: latestContext.meta?.location?.preference || analysisMeta?.location?.preference || locationPreference,
              location_value: latestContext.meta?.location?.value || analysisMeta?.location?.value || locationValue,
            },
          }),
        });
      } else {
        response = await fetch(apiUrl("/api/research"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            topic: payload.refined_query,
            section: resultSection,
            queries: Array.isArray(payload?.new_queries) ? payload.new_queries : [],
            follow_up_mode: true,
            existing_chunks: existingChunks,
            debug: true,
            ...buildLocationPayload(
              latestContext.meta?.location?.preference || analysisMeta?.location?.preference || locationPreference,
              latestContext.meta?.location?.value || analysisMeta?.location?.value || locationValue,
            ),
          }),
        });
      }

      let responsePayload = null;
      try {
        responsePayload = await response.json();
      } catch {
        responsePayload = null;
      }

      if (!response.ok) {
        throw new Error(buildErrorMessage(responsePayload, "Follow-up research failed. Please try again."));
      }
      const normalizedFollowUpPayload = normalizeResearchResponse(responsePayload, resultSection);
      if (!normalizedFollowUpPayload) {
        throw new Error("Follow-up research returned an unexpected response shape.");
      }

      const results = extractResearchItems(normalizedFollowUpPayload);

      const nextEntry = {
        id: `followup-${Date.now()}`,
        status: "completed",
        query: followUpPending.query,
        refined_query: payload.refined_query,
        decision,
        reason: String(payload?.reason || "").trim(),
        new_queries: Array.isArray(payload?.new_queries) ? payload.new_queries : [],
        results,
        result: normalizedFollowUpPayload,
        title: String(normalizedFollowUpPayload?.title || followUpSectionTitle(payload.refined_query, resultSection)).trim(),
        section: normalizedFollowUpPayload?.section || resultSection,
        meta: normalizedFollowUpPayload?.meta || analysisMeta,
        debug: normalizedFollowUpPayload?.debug || analysisDebug,
      };

      setFollowUps((current) => [...current, nextEntry]);
      setFollowUpPending(null);
      setFollowUpDraft("");
      setFollowUpQuery("");
      setFollowUpOpen(false);
    } catch (error) {
      setFollowUpPending({
        id: `followup-error-${Date.now()}`,
        status: "confirming",
        query: followUpPending.query,
        refined_query: payload.refined_query,
        payload,
        reason:
          error instanceof Error
            ? error.message
            : "Insufficient data found. Expanding research...",
      });
    } finally {
      setIsProcessing(false);
    }
  }

  function editFollowUpRefinement() {
    setFollowUpPending((current) =>
      current
        ? {
            ...current,
            refined_query: String(followUpDraft || current.refined_query || "").trim() || current.refined_query,
          }
        : current,
    );
    setFollowUpOpen(true);
  }

  async function handleFollowUpSubmit(event) {
    event.preventDefault();
    if (isProcessing) {
      return;
    }
    await requestFollowUpDecision(followUpQuery);
  }

  async function handleAnalyze(event) {
    event.preventDefault();
    if (isProcessing) {
      return;
    }

    const trimmedTopic = topic.trim();
    if (!trimmedTopic) {
      setAnalysisError("Enter a topic before running analysis.");
      setAnalysisState("error");
      return;
    }

    if (locationPreference !== "global" && !locationValue) {
      setAnalysisError("Select a region or country before launching a location-specific run.");
      setAnalysisState("error");
      return;
    }

    const requestedLocation = deriveLocationMeta(
      locationPreference,
      locationValue,
      locations.countries,
    );

    flushSync(() => {
      setIsProcessing(true);
      setAnalysisError("");
      setProgressValue((current) => Math.max(current, 12));
      setLoaderFrameId((current) => current + 1);
      setWorkspaceSurfaceState("transitioning");
      setLiveJournal([
        {
          id: `journal-${Date.now()}-launch`,
          message: LIVE_JOURNAL[0],
        },
      ]);
      setAnalysisState("analyzing");
      setAnalysisResult(null);
      setAnalysisDebug(null);
      resetFollowUps();
      setAnalysisMeta({
        topic: trimmedTopic,
        location: requestedLocation,
      });
    });

    await new Promise((resolve) => {
      window.requestAnimationFrame(() => resolve());
    });

    try {
      const response = await fetch(apiUrl("/api/research"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          topic: trimmedTopic,
          section,
          debug: true,
          ...buildLocationPayload(locationPreference, locationValue),
        }),
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      if (!response.ok) {
        throw new Error(buildErrorMessage(payload, "Analysis failed. Please try again."));
      }

      if (payload?.error) {
        throw new Error(payload.error);
      }

      const normalizedPayload = normalizeResearchResponse(payload, section);
      if (!normalizedPayload) {
        throw new Error("Analysis returned an unexpected response shape.");
      }

      startTransition(() => {
        const responseMeta = {
          topic: normalizedPayload?.meta?.topic || trimmedTopic,
          location: normalizedPayload?.meta?.location || requestedLocation,
        };
        setAnalysisResult(normalizedPayload);
        setAnalysisDebug(normalizedPayload.debug || null);
        setAnalysisMeta(responseMeta);
        setProgressValue((current) => Math.max(current, 100));
        setLiveJournal(buildCompletedJournal(normalizedPayload, normalizedPayload.debug || null, responseMeta));
        setAnalysisState("completed");
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Analysis failed. Please try again.";
      setAnalysisError(message);
      setAnalysisState("error");
      setProgressValue(0);
      setLiveJournal([
        {
          id: `journal-${Date.now()}-error`,
          message,
        },
      ]);
    } finally {
      setIsProcessing(false);
    }
  }

  return html`
    <div className="workspace-shell relative min-h-full overflow-x-hidden">
      <div className="workspace-grid relative z-10 grid min-h-full grid-rows-[auto_auto_minmax(0,1fr)] gap-3 px-3 py-3 md:gap-4 md:px-4 md:py-4 xl:px-5 xl:py-5">
        <${WorkspaceHeader}
          currentLocation=${displayMeta.location}
        />

        <${CommandDeck}
          topic=${topic}
          section=${section}
          locationPreference=${locationPreference}
          locationValue=${locationValue}
          secondaryFilterOpen=${secondaryFilterOpen}
          locations=${locations}
          analysisError=${analysisState === "error" ? analysisError : ""}
          locationLoadError=${locationLoadError}
          isProcessing=${isProcessing}
          regionQuery=${regionQuery}
          countryQuery=${countryQuery}
          filteredRegions=${filteredRegions}
          filteredCountries=${filteredCountries}
          allCountriesCount=${allCountriesCount}
          onTopicChange=${setTopic}
          onSectionChange=${setSection}
          onPreferenceChange=${setLocationPreference}
          onRegionQueryChange=${setRegionQuery}
          onCountryQueryChange=${setCountryQuery}
          onLocationSelect=${setLocationValue}
          onOpenSecondaryFilter=${() => setSecondaryFilterOpen(true)}
          onCloseSecondaryFilter=${() => setSecondaryFilterOpen(false)}
          onAnalyze=${handleAnalyze}
        />

        ${showWorkspacePanels
          ? html`
              <div className="relative min-h-0">
                <div
                  className=${cx(
                    "workspace-main grid min-h-0 gap-4 transition-opacity duration-200 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]",
                    isWorkspaceTransitioning ? "opacity-0" : "opacity-100",
                  )}
                >
                  <${FieldNotesPane}
                    analysisState=${analysisState}
                    result=${analysisResult}
                    debug=${analysisDebug}
                    meta=${displayMeta}
                    analysisError=${analysisError}
                    liveJournal=${liveJournal}
                    progressValue=${progressValue}
                    reducedMotion=${reducedMotion}
                  />

                  <${BriefingCanvas}
                    analysisState=${analysisState}
                    result=${analysisResult}
                    debug=${analysisDebug}
                    meta=${displayMeta}
                  analysisError=${analysisError}
                  progressValue=${progressValue}
                  onLoaderReady=${handleBriefingLoaderReady}
                  loaderFrameId=${loaderFrameId}
                  onDownload=${handleDownloadResults}
                  exportPending=${exportPending}
                  followUpOpen=${followUpOpen}
                  followUpQuery=${followUpQuery}
                  followUpDraft=${followUpDraft}
                    followUpPending=${followUpPending}
                    followUps=${followUps}
                    isProcessing=${isProcessing}
                    onToggleFollowUp=${toggleFollowUpComposer}
                    onFollowUpQueryChange=${setFollowUpQuery}
                    onFollowUpDraftChange=${setFollowUpDraft}
                    onFollowUpSubmit=${handleFollowUpSubmit}
                    onFollowUpConfirm=${finalizeFollowUp}
                    onFollowUpEdit=${editFollowUpRefinement}
                  />
                </div>

                <${AnimatePresence} initial=${false}>
                  ${isWorkspaceTransitioning
                    ? html`<${WorkspaceTransitionShell} key="workspace-transition" />`
                    : null}
                </${AnimatePresence}>
              </div>
            `
          : null}
      </div>
    </div>
  `;
}

const rootElement = document.getElementById("root");

if (rootElement) {
  createRoot(rootElement).render(html`<${App} />`);
}
