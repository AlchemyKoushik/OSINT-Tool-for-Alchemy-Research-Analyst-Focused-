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
import { mountApp } from "./components/app-root.js";
import { createResearchJobPoller } from "./hooks/use-research-job-polling.js";
import { RESEARCH_PAGE_ID } from "./pages/research-page.js";
import { buildJobProgressMessage } from "./utils/research-utils.js";

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

function buildFeatureFlags(section) {
  return String(section || "").trim() === "competitive_landscape"
    ? { competitive_landscape_v2: true }
    : {};
}

const BASE_SECTION_OPTIONS = [
  { value: "trends", label: "Trends" },
  { value: "drivers", label: "Drivers" },
  { value: "competitive_landscape", label: "Competitive Landscape (CL)" },
  { value: "industry_earnings_snapshot", label: "Industry Earnings Snapshot" },
];

function getClientConfig() {
  if (typeof window === "undefined" || !window.OSINT_CLIENT_CONFIG || typeof window.OSINT_CLIENT_CONFIG !== "object") {
    return {};
  }
  return window.OSINT_CLIENT_CONFIG;
}

function getEnabledSections() {
  const configuredSections = Array.isArray(getClientConfig().enabledSections)
    ? getClientConfig().enabledSections.map((value) => String(value || "").trim()).filter(Boolean)
    : [];
  const normalized = configuredSections.filter((value, index) =>
    BASE_SECTION_OPTIONS.some((option) => option.value === value) && configuredSections.indexOf(value) === index,
  );
  return normalized.length ? normalized : BASE_SECTION_OPTIONS.map((option) => option.value);
}

function isFollowUpEnabled() {
  return getClientConfig().followUpEnabled !== false;
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

const SECTION_OPTIONS = BASE_SECTION_OPTIONS.filter((option) => getEnabledSections().includes(option.value));

const INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS = [
  { value: "top_10", label: "Top 10" },
  { value: "top_20", label: "Top 20" },
  { value: "top_50", label: "Top 50" },
];
let cachedIesCatalog = null;
let cachedIesCatalogPromise = null;

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
  if (!section) {
    return "Select a Module";
  }
  if (section === "drivers") {
    return "Market Drivers";
  }
  if (section === "competitive_landscape") {
    return "Competitive Landscape";
  }
  if (section === "industry_earnings_snapshot") {
    return "Industry Earnings Snapshot";
  }
  return "Industry Trends";
}

function sectionDescriptor(section) {
  if (!section) {
    return "Choose a module from the fixed selector above to expand the input pane and unlock the run controls.";
  }
  if (section === "drivers") {
    return "Underlying forces accelerating or shaping the market.";
  }
  if (section === "competitive_landscape") {
    return "Key players and other players separated into memo-ready company profiles, with recent developments from the last 2 to 3 years.";
  }
  if (section === "industry_earnings_snapshot") {
    return "Choose a sector, industry, country, and Top N to build a focused earnings snapshot.";
  }
  return "Observable patterns, shifts, and momentum lines across the landscape.";
}

function getOptionLabel(options, value, fallback = "") {
  const normalizedValue = String(value || "").trim();
  const match = Array.isArray(options)
    ? options.find((option) => String(option?.value || "").trim() === normalizedValue)
    : null;
  return String(match?.label || fallback || "").trim();
}

function buildIndustryEarningsSnapshotTopic({
  sectorOptions,
  industriesBySector,
  coverageOptions,
  sector,
  industry,
  coverage,
  locationLabel,
}) {
  const sectorLabel = getOptionLabel(Array.isArray(sectorOptions) ? sectorOptions : [], sector, sector);
  const industryLabel = getOptionLabel(
    (industriesBySector && industriesBySector[String(sector || "").trim()]) || [],
    industry,
    industry,
  );
  const coverageLabel = getOptionLabel(
    Array.isArray(coverageOptions) ? coverageOptions : INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS,
    coverage,
    coverage,
  );
  const locationText = String(locationLabel || "").trim();

  const titleParts = [industryLabel || sectorLabel].filter(Boolean);
  const scopeParts = [locationText, coverageLabel].filter(Boolean);

  if (!titleParts.length && !scopeParts.length) {
    return "Industry Earnings Snapshot";
  }

  const titleText = titleParts.length ? titleParts.join(" / ") : "Industry Earnings Snapshot";
  return scopeParts.length ? `${titleText} | ${scopeParts.join(" | ")}` : titleText;
}

function getIesReportTopN(snapshotCoverage) {
  const normalized = String(snapshotCoverage || "").trim().toLowerCase();
  const parsed = Number.parseInt(normalized.replace(/^top_/, ""), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : 10;
}

function getIesReportScope(preference, value) {
  const normalizedPreference = String(preference || "").trim().toLowerCase();
  const normalizedValue = String(value || "").trim();

  if (normalizedPreference === "global") {
    return {
      filter_type: "global",
      filter_value: null,
      label: "Global",
      scopeLabel: "Scope",
    };
  }

  if (normalizedPreference === "region_specific") {
    return {
      filter_type: "region",
      filter_value: normalizedValue || null,
      label: normalizedValue || "Region not selected",
      scopeLabel: "Region",
    };
  }

  return {
    filter_type: "country",
    filter_value: normalizedValue || null,
    label: normalizedValue || "Country not selected",
    scopeLabel: "Country",
  };
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
    if (fallbackSection === "industry_earnings_snapshot") {
      return "Follow-up Earnings Snapshot";
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

  if (fallbackSection === "industry_earnings_snapshot") {
    return normalized
      .split(/\s+/)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
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
    market_role: String(item.market_role || item.role || item.company_role || "").trim(),
    key_company_facts: Array.isArray(item.key_company_facts || item.key_facts || item.company_facts)
      ? (item.key_company_facts || item.key_facts || item.company_facts)
        .map((fact) => String(fact || "").trim())
        .filter((fact, index, facts) => fact && facts.indexOf(fact) === index)
        .slice(0, 7)
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
    payload.section === "trends" ||
      payload.section === "drivers" ||
      payload.section === "competitive_landscape" ||
      payload.section === "industry_earnings_snapshot"
      ? payload.section
      : Array.isArray(payload.drivers)
        ? "drivers"
        : Array.isArray(payload.competitive_landscape)
          ? "competitive_landscape"
          : Array.isArray(payload.industry_earnings_snapshot)
            ? "industry_earnings_snapshot"
            : Array.isArray(payload.trends)
              ? "trends"
              : fallbackSection;
  const normalizedMajorPlayers =
    inferredSection === "competitive_landscape" && Array.isArray(payload.major_players)
      ? payload.major_players.map(normalizeResearchItem).filter(Boolean)
      : [];
  const normalizedEmergingPlayers =
    inferredSection === "competitive_landscape" && Array.isArray(payload.emerging_players)
      ? payload.emerging_players.map(normalizeResearchItem).filter(Boolean)
      : [];
  const rawItems = Array.isArray(payload.items)
    ? payload.items
    : Array.isArray(payload[inferredSection])
      ? payload[inferredSection]
      : [];
  const normalizedItems =
    inferredSection === "competitive_landscape"
      ? [...normalizedMajorPlayers, ...normalizedEmergingPlayers]
      : rawItems.map(normalizeResearchItem).filter(Boolean);
  const title = String(payload.title || payload.heading || sectionTitle(inferredSection)).trim() || sectionTitle(inferredSection);

  return {
    ...payload,
    section: inferredSection,
    title,
    major_players: normalizedMajorPlayers,
    emerging_players: normalizedEmergingPlayers,
    items: normalizedItems,
  };
}

function isIesReportPayload(payload) {
  return Boolean(
    payload &&
    typeof payload === "object" &&
    Array.isArray(payload.companies) &&
    payload.summary &&
    payload.scatter_chart,
  );
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeIesCompany(company) {
  if (!company || typeof company !== "object") {
    return null;
  }

  const normalized = {
    canonical_company_id: String(company.canonical_company_id || "").trim(),
    ticker: String(company.ticker || "").trim(),
    company_name: String(company.company_name || "").trim(),
    sector: String(company.sector || "").trim(),
    industry: String(company.industry || "").trim(),
    listing_country: String(company.listing_country || "").trim(),
    listing_region: String(company.listing_region || "").trim(),
    listing_exchange: String(company.listing_exchange || "").trim(),
    company_country: String(company.company_country || "").trim(),
    company_region: String(company.company_region || "").trim(),
    company_exchange: String(company.company_exchange || "").trim(),
    country: String(company.country || company.company_country || "").trim(),
    region: String(company.region || company.company_region || "").trim(),
    exchange: String(company.exchange || company.company_exchange || "").trim(),
    currency: String(company.currency || "").trim(),
    revenue_ttm: toNumberOrNull(company.revenue_ttm),
    market_cap: toNumberOrNull(company.market_cap),
    enterprise_value: toNumberOrNull(company.enterprise_value),
    current_ev: toNumberOrNull(company.current_ev),
    ebitda_ttm: toNumberOrNull(company.ebitda_ttm),
    revenue_growth_lq_yoy: toNumberOrNull(company.revenue_growth_lq_yoy),
    operating_margin: toNumberOrNull(company.operating_margin),
    ebitda_margin: toNumberOrNull(company.ebitda_margin),
    ev_to_revenue_ttm: toNumberOrNull(company.ev_to_revenue_ttm),
    ev_to_ebitda_ttm: toNumberOrNull(company.ev_to_ebitda_ttm),
    reported_eps: toNumberOrNull(company.reported_eps),
    eps_estimate: toNumberOrNull(company.eps_estimate),
    eps_surprise: toNumberOrNull(company.eps_surprise),
    forward_pe: toNumberOrNull(company.forward_pe),
    five_day_price_reaction: toNumberOrNull(company.five_day_price_reaction),
    latest_earnings_date: String(company.latest_earnings_date || "").trim(),
    earnings_reference_date: String(company.earnings_reference_date || "").trim(),
    last_reported_earnings_date: String(company.last_reported_earnings_date || "").trim(),
    last_reported_eps: toNumberOrNull(company.last_reported_eps),
    last_reported_eps_estimate: toNumberOrNull(company.last_reported_eps_estimate),
    last_reported_eps_surprise: toNumberOrNull(company.last_reported_eps_surprise),
    next_earnings_date: String(company.next_earnings_date || "").trim(),
    next_eps_estimate: toNumberOrNull(company.next_eps_estimate),
    enrichment_status: String(company.enrichment_status || "").trim(),
    enrichment_error: String(company.enrichment_error || "").trim(),
    metric_sources: company.metric_sources && typeof company.metric_sources === "object" ? company.metric_sources : {},
    validation_warnings: Array.isArray(company.validation_warnings)
      ? company.validation_warnings.map((warning) => String(warning || "").trim()).filter(Boolean)
      : [],
    outlier_metrics: Array.isArray(company.outlier_metrics)
      ? company.outlier_metrics.map((metric) => String(metric || "").trim()).filter(Boolean)
      : [],
    is_outlier: Boolean(company.is_outlier),
  };

  return normalized.ticker || normalized.company_name ? normalized : null;
}

function normalizeIesScatterPoint(point) {
  if (!point || typeof point !== "object") {
    return null;
  }

  const normalized = {
    ticker: String(point.ticker || "").trim(),
    company_name: String(point.company_name || "").trim(),
    revenue_growth_lq_yoy: toNumberOrNull(point.revenue_growth_lq_yoy),
    operating_margin: toNumberOrNull(point.operating_margin),
    bubble_size: toNumberOrNull(point.bubble_size),
    is_outlier: Boolean(point.is_outlier),
  };

  return normalized.ticker || normalized.company_name ? normalized : null;
}

function normalizeIesReportResponse(payload) {
  if (!isIesReportPayload(payload)) {
    return null;
  }

  const request = payload.request && typeof payload.request === "object" ? payload.request : {};
  const summary = payload.summary && typeof payload.summary === "object" ? payload.summary : {};
  const scatterChart = payload.scatter_chart && typeof payload.scatter_chart === "object" ? payload.scatter_chart : {};
  const metadata = payload.metadata && typeof payload.metadata === "object" ? payload.metadata : {};
  const companies = Array.isArray(payload.companies) ? payload.companies.map(normalizeIesCompany).filter(Boolean) : [];
  const scatterData = Array.isArray(scatterChart.data)
    ? scatterChart.data.map(normalizeIesScatterPoint).filter(Boolean)
    : [];
  const industry = String(summary.industry || request.industry || "").trim();
  const normalizedFilterType = String(
    summary.filter_type || request.filter_type || (request.country || summary.country ? "country" : ""),
  )
    .trim()
    .toLowerCase();
  const rawFilterValue = String(
    summary.filter_value || request.filter_value || request.country || summary.country || "",
  ).trim();
  const topN = toNumberOrNull(summary.requested_top_n || request.top_n);
  const scopeInfo = getIesReportScope(
    normalizedFilterType === "region" ? "region_specific" : normalizedFilterType === "global" ? "global" : "country_specific",
    rawFilterValue,
  );
  const title = [industry, scopeInfo.label].filter(Boolean).join(" | ") || "Industry Earnings Snapshot";
  const locationLabel = scopeInfo.label || "Global";

  return {
    ...payload,
    section: "industry_earnings_snapshot",
    report_type: "ies_report",
    title,
    request: {
      industry,
      filter_type: scopeInfo.filter_type,
      filter_value: scopeInfo.filter_value,
      country: scopeInfo.filter_type === "country" ? scopeInfo.filter_value : "",
      top_n: Number.isFinite(topN) ? topN : toNumberOrNull(request.top_n),
    },
    summary: {
      ...summary,
      industry,
      filter_type: scopeInfo.filter_type,
      filter_value: scopeInfo.filter_value,
      country: scopeInfo.filter_type === "country" ? scopeInfo.filter_value : "",
      requested_top_n: Number.isFinite(topN) ? topN : toNumberOrNull(summary.requested_top_n || request.top_n),
    },
    scatter_chart: {
      title: String(scatterChart.title || "Peer Positioning").trim(),
      x_label: String(scatterChart.x_label || "Revenue Growth (LQ YoY)").trim(),
      y_label: String(scatterChart.y_label || "Operating Margin").trim(),
      bubble_size_label: String(scatterChart.bubble_size_label || "Revenue TTM").trim(),
      data: scatterData,
    },
    companies,
    metadata: {
      ...metadata,
      note: String(metadata.note || "").trim(),
    },
    meta: {
      topic: title,
      location: {
        preference:
          scopeInfo.filter_type === "global"
            ? "global"
            : scopeInfo.filter_type === "region"
              ? "region_specific"
              : "country_specific",
        scope: scopeInfo.filter_type,
        label: locationLabel,
        value: scopeInfo.filter_value || "",
        region: scopeInfo.filter_type === "region" ? scopeInfo.filter_value || "" : "",
        strict: scopeInfo.filter_type !== "global",
      },
    },
  };
}

function buildDownloadFileName(result, meta) {
  const scope = slugifyFilenamePart(meta?.location?.label || "global", "global");
  const topic = slugifyFilenamePart(meta?.topic || result?.title || "industry-brief", "industry-brief");
  const section = slugifyFilenamePart(result?.section || "trends", "trends");
  return `${topic}-${section}-${scope}-${formatPreparedDateForFile()}.html`;
}

function buildExportSources(sources) {
  if (!Array.isArray(sources)) {
    return [];
  }
  return sources
    .map((source) => ({
      title: String(source?.title || "").trim(),
      url: String(source?.url || "").trim(),
      domain: String(source?.domain || "").trim(),
      date: String(source?.date || source?.published_date || "").trim(),
    }))
    .filter((source) => source.title || source.url || source.domain || source.date)
    .slice(0, 5);
}

function buildExportExamples(examples) {
  if (!Array.isArray(examples)) {
    return [];
  }
  return examples
    .map((example) => ({
      text: String(example?.text || "").trim(),
      year: String(example?.year || example?.event_date || example?.published_date || "").trim(),
      why_it_matters: String(example?.why_it_matters || example?.trend_fit_reason || "").trim(),
    }))
    .filter((example) => example.text)
    .slice(0, 5);
}

function buildExportItem(item) {
  const normalizedItem = item && typeof item === "object" ? item : {};
  return {
    heading: String(normalizedItem?.heading || normalizedItem?.title || "").trim(),
    body: String(normalizedItem?.body || normalizedItem?.description || "").trim(),
    segment: String(normalizedItem?.segment || "").trim(),
    market_role: String(normalizedItem?.market_role || "").trim(),
    key_company_facts: Array.isArray(normalizedItem?.key_company_facts)
      ? normalizedItem.key_company_facts
        .map((fact) => String(fact || "").trim())
        .filter(Boolean)
        .slice(0, 5)
      : [],
    competitive_positioning: String(normalizedItem?.competitive_positioning || "").trim(),
    examples: buildExportExamples(normalizedItem?.examples),
    recent_strategic_developments: buildExportExamples(normalizedItem?.recent_strategic_developments),
    sources: buildExportSources(normalizedItem?.sources),
  };
}

function buildExportResultPayload(result) {
  const normalizedResult = result && typeof result === "object" ? result : {};
  const section = String(normalizedResult?.section || "trends").trim() || "trends";
  const payload = {
    section,
    title: String(normalizedResult?.title || "").trim(),
  };

  if (section === "competitive_landscape") {
    payload.major_players = Array.isArray(normalizedResult?.major_players)
      ? normalizedResult.major_players.map(buildExportItem).filter((item) => item.heading || item.body)
      : [];
    payload.emerging_players = Array.isArray(normalizedResult?.emerging_players)
      ? normalizedResult.emerging_players.map(buildExportItem).filter((item) => item.heading || item.body)
      : [];
    payload.items = [...payload.major_players, ...payload.emerging_players];
    return payload;
  }

  payload.items = Array.isArray(normalizedResult?.items)
    ? normalizedResult.items.map(buildExportItem).filter((item) => item.heading || item.body)
    : [];
  return payload;
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
        ...buildExportResultPayload(
          Array.isArray(entry?.results)
            ? { section: entry?.section || result?.section, items: entry.results }
            : entry?.result,
        ),
        meta: entry?.meta || meta,
      }))
    : [];
  const payload = {
    result: buildExportResultPayload(result),
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

function isIesCatalog(payload) {
  return payload && typeof payload === "object" && Array.isArray(payload.sectors);
}

function normalizeIesCatalogOption(value) {
  if (value && typeof value === "object") {
    const normalizedValue = String(value.value || value.label || value.sector || value.industry || "").trim();
    const normalizedLabel = String(value.label || value.value || value.sector || value.industry || "").trim();
    if (!normalizedValue && !normalizedLabel) {
      return null;
    }
    return {
      value: normalizedValue || normalizedLabel,
      label: normalizedLabel || normalizedValue,
    };
  }

  const normalized = String(value || "").trim();
  if (!normalized) {
    return null;
  }
  return { value: normalized, label: normalized };
}

function normalizeIesCatalog(payload) {
  if (!isIesCatalog(payload)) {
    return null;
  }

  const sectorsInput = Array.isArray(payload.sectors) ? payload.sectors : [];
  const industriesBySectorInput = payload.industries_by_sector || payload.industriesBySector || {};
  const sectors = [];
  const industriesBySector = {};
  const seenSectors = new Set();

  sectorsInput.forEach((entry) => {
    const sectorValue =
      typeof entry === "string"
        ? entry
        : String(entry?.value || entry?.label || entry?.sector || "").trim();
    if (!sectorValue) {
      return;
    }

    const sectorKey = sectorValue.toLowerCase();
    if (seenSectors.has(sectorKey)) {
      return;
    }
    seenSectors.add(sectorKey);

    const sectorIndustriesRaw =
      industriesBySectorInput[sectorValue] ||
      industriesBySectorInput[entry?.value] ||
      industriesBySectorInput[entry?.label] ||
      [];
    const normalizedIndustries = Array.isArray(sectorIndustriesRaw)
      ? sectorIndustriesRaw.map(normalizeIesCatalogOption).filter(Boolean)
      : [];

    sectors.push({
      value: sectorValue,
      label: sectorValue,
      industry_count: normalizedIndustries.length,
    });
    industriesBySector[sectorValue] = normalizedIndustries;
  });

  if (!sectors.length) {
    return null;
  }

  return {
    sectors,
    industriesBySector,
  };
}

async function loadIesCatalog() {
  if (cachedIesCatalog) {
    return cachedIesCatalog;
  }

  if (!cachedIesCatalogPromise) {
    cachedIesCatalogPromise = (async () => {
      const response = await fetch(apiUrl("/api/ies-catalog"));
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      const normalizedCatalog = normalizeIesCatalog(payload);
      if (!response.ok || !normalizedCatalog) {
        throw new Error("The IES catalog could not be loaded from the database.");
      }

      cachedIesCatalog = normalizedCatalog;
      return normalizedCatalog;
    })();
  }

  try {
    return await cachedIesCatalogPromise;
  } finally {
    cachedIesCatalogPromise = null;
  }
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
    if (Array.isArray(payload.detail) && payload.detail.length && typeof payload.detail[0]?.msg === "string") {
      return payload.detail[0].msg;
    }
    if (typeof payload.error === "string" && payload.error.trim()) {
      return payload.error;
    }
  }
  return fallbackMessage;
}

function buildCompletedJournal(result, debug, meta) {
  if (isIesReportPayload(result)) {
    const request = result.request || {};
    const summary = result.summary || {};
    const companiesReturned = Number(summary.companies_returned || result.companies?.length || 0);
    const companiesEnriched = Number(summary.companies_enriched || 0);
    const scatterCount = Array.isArray(result.scatter_chart?.data) ? result.scatter_chart.data.length : 0;
    const scopeInfo = getIesReportScope(
      request.filter_type === "region"
        ? "region_specific"
        : request.filter_type === "global"
          ? "global"
          : "country_specific",
      request.filter_value || request.country || summary.filter_value || summary.country || "",
    );
    return [
      {
        id: "journal-scope",
        message: `Scoped the report to ${request.industry || "the selected industry"} in ${scopeInfo.label} with Top ${request.top_n || 10}.`,
      },
      {
        id: "journal-universe",
        message: `Returned ${companiesReturned || "no"} companies after deduplication and filtering.`,
      },
      {
        id: "journal-enrichment",
        message: `${companiesEnriched || 0} companies completed enrichment for the final memo.`,
      },
      {
        id: "journal-output",
        message: `Rendered ${scatterCount || 0} scatter points and ${result.companies?.length || 0} company rows in the final canvas.`,
      },
    ];
  }

  const queries = Array.isArray(debug?.queries) ? debug.queries : [];
  const selectedUrls = Array.isArray(debug?.selected_urls) ? debug.selected_urls : [];
  const sourceCount = Number(debug?.num_sources || selectedUrls.length || 0);
  const artifacts = debug?.artifact_counts || {};
  const outputLabel =
    result?.section === "drivers"
      ? "drivers"
      : result?.section === "competitive_landscape"
        ? "company profiles"
        : result?.section === "industry_earnings_snapshot"
          ? "earnings snapshot insights"
          : "insights";

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
      message: `Delivered ${result?.items?.length || 0} memo-ready ${outputLabel} in the final canvas.`,
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
  placeholderLabel = "None",
  disabled = false,
  loading = false,
}) {
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState(null);
  const selectedOption = options.find((option) => option.value === value) || null;
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
        className=${cx(triggerClassName, loading && "is-loading")}
        aria-expanded=${open ? "true" : "false"}
        aria-haspopup="listbox"
        aria-controls=${listboxId}
        disabled=${disabled || loading}
        onClick=${toggleOpen}
        onKeyDown=${handleTriggerKeyDown}
      >
        <span className="command-select__value inline-flex items-center gap-2">
          ${loading
            ? html`
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-atelier-forest border-t-transparent shrink-0"></span>
                <span className="text-atelier-moss/70 font-medium">${placeholderLabel}</span>
              `
            : selectedOption
              ? selectedOption.label
              : placeholderLabel}
        </span>
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

function ModuleSelectorBar({ section, onSectionChange, disabled = false }) {
  return html`
    <${PanelShell} className="atelier-panel-strong module-selector-bar sticky-module-bar sticky top-3 z-20 px-4 py-4 md:px-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(18rem,auto)] xl:items-center">
        <div className="min-w-0">
          <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.28em] text-atelier-moss/72">
            Module Selection
          </p>
          <h2 className="m-0 font-display text-[1.45rem] font-semibold leading-none text-atelier-ink">
            Choose Your Research Module
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-atelier-moss">
            Choose a module to activate the corresponding research workflow.
          </p>
        </div>

        <div className="min-w-0">
          <${ThemedSelect}
            id="sectionSelect"
            options=${SECTION_OPTIONS}
            value=${section}
            onChange=${onSectionChange}
            disabled=${disabled}
          />
        </div>
      </div>
    </${PanelShell}>
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
  snapshotSector,
  snapshotIndustry,
  snapshotCoverage,
  snapshotSectorOptions,
  snapshotIndustryOptions,
  snapshotCatalogLoading,
  snapshotCatalogError,
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
  onSnapshotSectorChange,
  onSnapshotIndustryChange,
  onSnapshotCoverageChange,
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
  const isEarningsSnapshot = section === "industry_earnings_snapshot";
  const snapshotCoverageLabel =
    INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS.find((option) => option.value === snapshotCoverage)?.label || "";
  const snapshotReady = !snapshotCatalogLoading && !snapshotCatalogError && snapshotSectorOptions.length > 0;

  if (isEarningsSnapshot) {
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
          title="Design the earnings snapshot"
          subtitle="Create an earnings snapshot by sector, industry and geography."
        />

        <form className="mt-6 grid gap-4" onSubmit=${onAnalyze}>
          <div className=${cx("atelier-panel-strong rounded-[26px] px-4 py-4", isProcessing && "ui-disabled-shell")}>
            <div className="command-deck-grid grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_minmax(10rem,0.72fr)_minmax(14rem,0.82fr)_minmax(14.5rem,0.85fr)]">
                <div className="command-deck-field">
                  <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="snapshotSector">
                    Sector
                  </label>
                  <${ThemedSelect}
                    id="snapshotSector"
                    options=${snapshotSectorOptions}
                    value=${snapshotSector}
                    onChange=${onSnapshotSectorChange}
                    disabled=${isProcessing || snapshotCatalogLoading || !snapshotSectorOptions.length}
                    loading=${snapshotCatalogLoading}
                    placeholderLabel=${snapshotCatalogLoading
        ? "Loading Sectors..."
        : snapshotSectorOptions.length
          ? "Select Sector"
          : "No Sectors Found"}
                  />
                </div>

                <div className="command-deck-field">
                  <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="snapshotIndustry">
                    Industry
                  </label>
                  <${ThemedSelect}
                    id="snapshotIndustry"
                    options=${snapshotIndustryOptions}
                    value=${snapshotIndustry}
                    onChange=${onSnapshotIndustryChange}
                    disabled=${isProcessing || snapshotCatalogLoading || !snapshotSector || !snapshotIndustryOptions.length}
                    loading=${snapshotCatalogLoading}
                    placeholderLabel=${snapshotCatalogLoading
        ? "Loading Industries..."
        : snapshotSector
          ? snapshotIndustryOptions.length
            ? "Select Industry"
            : "No Industries Found"
          : "Choose Sector First"}
                  />
                </div>

                <div className="command-deck-field">
                  <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="snapshotCoverage">
                    Top N
                  </label>
                  <${ThemedSelect}
                    id="snapshotCoverage"
                    options=${INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS}
                    value=${snapshotCoverage}
                    onChange=${onSnapshotCoverageChange}
                    disabled=${isProcessing || snapshotCatalogLoading}
                    placeholderLabel="Select Top N"
                  />
                </div>

                <div className="command-deck-field">
                  <label className="mb-2 block text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72" for="snapshotLocationPreference">
                    Location Preference
                  </label>
                  <${ThemedSelect}
                    id="snapshotLocationPreference"
                    options=${locations.preferences}
                    value=${locationPreference}
                    onChange=${onPreferenceChange}
                    disabled=${isProcessing}
                  />
                </div>

                <div className="command-deck-action">
                  <${LaunchButton} disabled=${isProcessing || snapshotCatalogLoading || !snapshotReady} processing=${isProcessing} />
                </div>
              </div>
            </div>

            <div className="atelier-panel-strong rounded-[24px] px-4 py-4">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div className="min-w-0">
                  <p className="m-0 text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
                    Applied Filter
                  </p>
                  <p className="mt-2 text-sm font-bold text-atelier-ink">
                    ${locationPreference === "global"
        ? "Global"
        : locationValue
          ? `${humanizePreference(locationPreference)}: ${locationValue}`
          : humanizePreference(locationPreference)}
                  </p>
                  <p className="mt-2 text-xs leading-5 text-atelier-moss">
                    ${locationPreference === "global"
        ? "Global keeps the snapshot broad and unrestricted."
        : locationValue
          ? "The snapshot is narrowed to the chosen geography. Use the edit control if you want to change it."
          : "Choose a region or country to activate a scoped filter."}
                  </p>
                  <p className="mt-2 text-xs font-semibold uppercase tracking-[0.18em] text-atelier-moss/72">
                    ${snapshotSector && snapshotIndustry ? `${snapshotSector.replace(/_/g, " ")} / ${snapshotIndustry.replace(/_/g, " ")}` : "Sector or industry not yet selected"}
                    ${snapshotCoverageLabel ? ` | ${snapshotCoverageLabel}` : ""}
                  </p>
                </div>

                ${scopedFilterActive && locationValue
        ? html`
                      <div className="shrink-0">
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
                      key="snapshot-region-selector"
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
                      key="snapshot-country-selector"
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
          subtitle="Set the topic, confirm the module from the fixed header, apply the geographic lens, and launch a run that stays traceable from first query to final memo."
        />

        <form className="mt-6 grid gap-4" onSubmit=${onAnalyze}>
          <div className=${cx("atelier-panel-strong rounded-[26px] px-4 py-4", isProcessing && "ui-disabled-shell")}>
            <div className="command-deck-grid grid gap-4 xl:grid-cols-[minmax(0,2.4fr)_minmax(14.25rem,1fr)_minmax(14.5rem,0.8fr)]">
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

          <div className="atelier-panel-strong rounded-[24px] px-4 py-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <p className="m-0 text-[10px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
                  Applied Filter
                </p>
                <p className="mt-2 text-sm font-bold text-atelier-ink">
                  ${locationPreference === "global"
      ? "Global"
      : locationValue
        ? `${humanizePreference(locationPreference)}: ${locationValue}`
        : humanizePreference(locationPreference)}
                </p>
                <p className="mt-2 text-xs leading-5 text-atelier-moss">
                  ${locationPreference === "global"
      ? "Global keeps the run wide and unrestricted."
      : locationValue
        ? "The run is narrowed to the chosen geography. Use the edit control if you want to change it."
        : "Choose a region or country to activate a scoped filter."}
                </p>
              </div>

              ${scopedFilterActive && locationValue
      ? html`
                    <div className="shrink-0">
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
    <div className=${cx("metric-card-shell flex h-full flex-col items-center justify-center text-center rounded-[18px] px-3 py-3 min-w-0", toneClass)}>
      <p className="m-0 font-display text-[9px] md:text-[10px] font-medium uppercase tracking-wider text-atelier-moss/70 text-center truncate w-full" title=${label}>${label}</p>
      <p className="mt-1.5 font-display text-base md:text-lg font-semibold tracking-tight text-atelier-ink text-center truncate w-full" title=${value}>
        ${value}
      </p>
    </div>
  `;
}

function formatIesLabel(value, fallback = "N/A") {
  const normalized = String(value || "").trim();
  return normalized || fallback;
}

function formatIesDateLabel(value) {
  const normalized = String(value || "").trim();
  return normalized || "N/A";
}

function getIesMetricSourceCount(company) {
  const sourceMap = company?.metric_sources && typeof company.metric_sources === "object" ? company.metric_sources : {};
  return Object.keys(sourceMap).length;
}

function getIesDisplayCompanyKey(company, index = 0) {
  return String(company?.ticker || company?.company_name || `company-${index}`).trim();
}

function buildIesInsightRows(result) {
  const companies = Array.isArray(result?.companies) ? result.companies.filter(Boolean) : [];
  const summary = result?.summary || {};
  const chartPoints = Array.isArray(result?.scatter_chart?.data) ? result.scatter_chart.data.filter(Boolean) : [];
  const request = result?.request || {};

  const highestGrowth = [...companies]
    .filter((company) => Number.isFinite(Number(company?.revenue_growth_lq_yoy)))
    .sort((a, b) => Number(b.revenue_growth_lq_yoy) - Number(a.revenue_growth_lq_yoy))[0];

  const highestMargin = [...companies]
    .filter((company) => Number.isFinite(Number(company?.operating_margin)))
    .sort((a, b) => Number(b.operating_margin) - Number(a.operating_margin))[0];

  const valuationRevenueCandidates = companies
    .map((company) => Number(company?.ev_to_revenue_ttm))
    .filter((value) => Number.isFinite(value));
  const valuationEbitdaCandidates = companies
    .map((company) => Number(company?.ev_to_ebitda_ttm))
    .filter((value) => Number.isFinite(value));
  const valuationRevenueMin = valuationRevenueCandidates.length ? Math.min(...valuationRevenueCandidates) : null;
  const valuationRevenueMax = valuationRevenueCandidates.length ? Math.max(...valuationRevenueCandidates) : null;
  const valuationEbitdaMin = valuationEbitdaCandidates.length ? Math.min(...valuationEbitdaCandidates) : null;
  const valuationEbitdaMax = valuationEbitdaCandidates.length ? Math.max(...valuationEbitdaCandidates) : null;


  const highestGrowthLabel = highestGrowth
    ? `${highestGrowth.company_name || highestGrowth.ticker || "Company"} leads revenue growth at ${formatIesPercent(highestGrowth.revenue_growth_lq_yoy)}.`
    : "Revenue growth leadership is not available in the current universe.";
  const highestMarginLabel = highestMargin
    ? `${highestMargin.company_name || highestMargin.ticker || "Company"} shows the highest operating margin at ${formatIesPercent(highestMargin.operating_margin)}.`
    : "Operating margin leadership is not available in the current universe.";
  const valuationLabelText = [
    valuationRevenueMin !== null && valuationRevenueMax !== null
      ? `EV / Revenue spans ${formatIesRatio(valuationRevenueMin)} to ${formatIesRatio(valuationRevenueMax)} across the universe.`
      : "EV / Revenue could not be derived from the available companies.",
    valuationEbitdaMin !== null && valuationEbitdaMax !== null
      ? `EV / EBITDA spans ${formatIesRatio(valuationEbitdaMin)} to ${formatIesRatio(valuationEbitdaMax)} across the universe.`
      : "EV / EBITDA could not be derived from the available companies.",
  ].join("\n");

  return {
    summary:
      "This memo presents peer data for the selected companies to support industry analysis and comparison.",
    rows: [
      {
        label: "Highest Growth",
        body: highestGrowthLabel,
        tone: "accent",
        icon: html`<svg className="w-4 h-4 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" /><polyline points="17 6 23 6 23 12" /></svg>`,
      },
      {
        label: "Highest Margin",
        body: highestMarginLabel,
        tone: "gold",
        icon: html`<svg className="w-4 h-4 text-amber-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></svg>`,
      },
      {
        label: "Valuation Range",
        body: valuationLabelText,
        tone: "slate",
        icon: html`<svg className="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /></svg>`,
      },
    ],
  };
}

function IesFieldGrid({ fields = [] }) {
  const normalizedFields = Array.isArray(fields)
    ? fields
      .map((field) => ({
        label: String(field?.label || "").trim(),
        value: String(field?.value || "").trim(),
      }))
      .filter((field) => field.label)
    : [];

  if (!normalizedFields.length) {
    return null;
  }

  return html`
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      ${normalizedFields.map(
    (field) => html`
          <div className="rounded-[20px] border border-atelier-line bg-white/78 px-4 py-4">
            <dt className="text-[10px] font-bold uppercase tracking-[0.22em] text-atelier-moss/64">
              ${field.label}
            </dt>
            <dd className="mt-2 text-sm leading-7 text-atelier-ink">
              ${field.value || "N/A"}
            </dd>
          </div>
        `,
  )}
    </dl>
  `;
}

function IesCompanyDrawerSection({ title, fields }) {
  const normalizedFields = Array.isArray(fields) ? fields.filter((field) => field?.label) : [];

  if (!normalizedFields.length) {
    return null;
  }

  return html`
    <section className="ies-drawer__section">
      <div className="flex items-end justify-between gap-3">
        <h5 className="m-0 text-[9px] font-bold uppercase tracking-[0.24em] text-atelier-moss/72">
          ${title}
        </h5>
        <span className="text-[8px] font-bold uppercase tracking-[0.18em] text-atelier-moss/50">
          ${normalizedFields.length} fields
        </span>
      </div>
      <div className="mt-3">
        <${IesFieldGrid} fields=${normalizedFields} />
      </div>
    </section>
  `;
}

function IesCompanyDrawer({ company, open, onClose }) {
  const [renderedCompany, setRenderedCompany] = useState(company || null);

  useEffect(() => {
    if (open && company) {
      setRenderedCompany(company);
    }
  }, [company, open]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    function handleKeyDown(event) {
      if (event.key === "Escape") {
        onClose();
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const portalRoot = getFloatingLayerRoot();

  if (!portalRoot) {
    return null;
  }

  return createPortal(
    html`
      <${AnimatePresence} initial=${false}>
        ${open && renderedCompany
        ? html`
              <${motion.div}
                key="ies-company-drawer"
                className="ies-drawer fixed inset-0 z-[190] flex items-stretch justify-end"
                initial=${{ opacity: 0 }}
                animate=${{ opacity: 1 }}
                exit=${{ opacity: 0 }}
                transition=${TRANSITION}
              >
                <button
                  type="button"
                  className="ies-drawer__backdrop absolute inset-0 border-0 bg-[#1a211d]/28 backdrop-blur-[2px]"
                  aria-label="Close company details"
                  onClick=${onClose}
                ></button>

                <${motion.aside}
                  className="ies-drawer__panel relative z-10 flex h-full w-full max-w-[44rem] flex-col overflow-hidden border-l border-atelier-line bg-[linear-gradient(180deg,rgba(255,253,248,0.98),rgba(248,242,232,0.98))] shadow-[0_30px_70px_rgba(31,42,41,0.16)]"
                  initial=${{ x: 38, opacity: 0 }}
                  animate=${{ x: 0, opacity: 1 }}
                  exit=${{ x: 38, opacity: 0 }}
                  transition=${TRANSITION}
                >
                  <div className="flex items-start justify-between gap-4 border-b border-atelier-line px-6 py-6 md:px-7">
                    <div className="min-w-0">
                      <p className="m-0 text-[10px] font-bold uppercase tracking-[0.26em] text-atelier-moss/66">
                        Company Dossier
                      </p>
                      <h4 className="mt-3 truncate font-display text-[2.2rem] font-semibold leading-none text-atelier-ink">
                        ${renderedCompany.company_name || renderedCompany.ticker || "Company"}
                      </h4>
                      <p className="mt-2 text-sm leading-7 text-atelier-moss">
                        ${renderedCompany.ticker || "N/A"} ${renderedCompany.exchange ? ` | ${renderedCompany.exchange}` : ""} ${renderedCompany.country ? ` | ${renderedCompany.country}` : ""}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick=${onClose}
                      className="filter-close-button mt-1"
                      aria-label="Close drawer"
                    >
                      <svg className="filter-close-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M7 7l10 10M17 7 7 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    </button>
                  </div>

                  <div className="panel-scroll flex-1 space-y-6 px-6 py-6 md:px-7">
                    <div className="rounded-[26px] border border-atelier-line bg-white/76 px-5 py-5">
                      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <${MetricCard} label="Revenue TTM" value=${formatIesCompactNumber(renderedCompany.revenue_ttm)} tone="accent" />
                        <${MetricCard} label="Market Cap" value=${formatIesCompactNumber(renderedCompany.market_cap)} />
                        <${MetricCard} label="EV / Revenue" value=${formatIesRatio(renderedCompany.ev_to_revenue_ttm)} />
                        <${MetricCard} label="EV / EBITDA" value=${formatIesRatio(renderedCompany.ev_to_ebitda_ttm)} tone="gold" />
                      </div>
                    </div>

                    <${IesCompanyDrawerSection}
                      title="Financial Performance"
                      fields=${[
            { label: "Revenue TTM", value: formatIesCompactNumber(renderedCompany.revenue_ttm) },
            { label: "Market Cap", value: formatIesCompactNumber(renderedCompany.market_cap) },
            { label: "Enterprise Value", value: formatIesCompactNumber(renderedCompany.enterprise_value) },
            { label: "Current EV", value: formatIesCompactNumber(renderedCompany.current_ev) },
            { label: "EBITDA TTM", value: formatIesCompactNumber(renderedCompany.ebitda_ttm) },
            { label: "Median Rev. Growth (LQ YoY)", value: formatIesPercent(renderedCompany.revenue_growth_lq_yoy) },
            { label: "Median Op. Margin (TTM)", value: formatIesPercent(renderedCompany.operating_margin) },
            { label: "Median EBITDA Margin (TTM)", value: formatIesPercent(renderedCompany.ebitda_margin) },
          ]}
                    />

                    <${IesCompanyDrawerSection}
                      title="Valuation"
                      fields=${[
            { label: "EV / Revenue", value: formatIesRatio(renderedCompany.ev_to_revenue_ttm) },
            { label: "EV / EBITDA", value: formatIesRatio(renderedCompany.ev_to_ebitda_ttm) },
            { label: "Forward P/E", value: formatIesRatio(renderedCompany.forward_pe) },
          ]}
                    />

                    <${IesCompanyDrawerSection}
                      title="Earnings"
                      fields=${[
            { label: "Reported EPS", value: formatIesLabel(Number.isFinite(renderedCompany.reported_eps) ? renderedCompany.reported_eps.toFixed(2) : "") },
            { label: "EPS Estimate", value: formatIesLabel(Number.isFinite(renderedCompany.eps_estimate) ? renderedCompany.eps_estimate.toFixed(2) : "") },
            { label: "EPS Surprise", value: formatIesPercent(renderedCompany.eps_surprise) },
            { label: "Last Reported EPS", value: formatIesLabel(Number.isFinite(renderedCompany.last_reported_eps) ? renderedCompany.last_reported_eps.toFixed(2) : "") },
            { label: "Last Reported Estimate", value: formatIesLabel(Number.isFinite(renderedCompany.last_reported_eps_estimate) ? renderedCompany.last_reported_eps_estimate.toFixed(2) : "") },
            { label: "Last Reported Surprise", value: formatIesPercent(renderedCompany.last_reported_eps_surprise) },
            { label: "Latest Earnings Date", value: formatIesDateLabel(renderedCompany.latest_earnings_date) },
            { label: "Last Reported Earnings Date", value: formatIesDateLabel(renderedCompany.last_reported_earnings_date) },
            { label: "Next Earnings Date", value: formatIesDateLabel(renderedCompany.next_earnings_date) },
            { label: "Next EPS Estimate", value: formatIesLabel(Number.isFinite(renderedCompany.next_eps_estimate) ? renderedCompany.next_eps_estimate.toFixed(2) : "") },
            { label: "5-Day Reaction", value: formatIesPercent(renderedCompany.five_day_price_reaction) },
          ]}
                    />

                    <${IesCompanyDrawerSection}
                      title="Flags"
                      fields=${[
            { label: "Enrichment Status", value: formatIesLabel(renderedCompany.enrichment_status) },
            { label: "Outlier", value: renderedCompany.is_outlier ? "Yes" : "No" },
            { label: "Outlier Metrics", value: outlierMetrics.length ? outlierMetrics.join(", ") : "None" },
            { label: "Validation Warnings", value: warnings.length ? warnings.join(" • ") : "None" },
            { label: "Enrichment Error", value: formatIesLabel(renderedCompany.enrichment_error) },
          ]}
                    />

                    <${IesCompanyDrawerSection}
                      title="Sources"
                      fields=${[
            { label: "Metric Source Count", value: sourceCount ? String(sourceCount) : "0" },
            ...sourceEntries.map(([key, value]) => ({
              label: key,
              value: typeof value === "object" ? JSON.stringify(value) : formatIesLabel(value),
            })),
          ]}
                    />

                    <${IesCompanyDrawerSection}
                      title="Notes"
                      fields=${[
            { label: "Canonical Company ID", value: formatIesLabel(renderedCompany.canonical_company_id) },
            { label: "Sector", value: formatIesLabel(renderedCompany.sector) },
            { label: "Industry", value: formatIesLabel(renderedCompany.industry) },
            { label: "Country", value: formatIesLabel(renderedCompany.country) },
            { label: "Region", value: formatIesLabel(renderedCompany.region) },
            { label: "Exchange", value: formatIesLabel(renderedCompany.exchange) },
            { label: "Currency", value: formatIesLabel(renderedCompany.currency) },
            { label: "Listing Country", value: formatIesLabel(renderedCompany.listing_country) },
            { label: "Listing Region", value: formatIesLabel(renderedCompany.listing_region) },
            { label: "Listing Exchange", value: formatIesLabel(renderedCompany.listing_exchange) },
            { label: "Company Country", value: formatIesLabel(renderedCompany.company_country) },
            { label: "Company Region", value: formatIesLabel(renderedCompany.company_region) },
            { label: "Company Exchange", value: formatIesLabel(renderedCompany.company_exchange) },
          ]}
                    />
                  </div>
                </${motion.aside}>
              </${motion.div}>
            `
        : null}
      </${AnimatePresence}>
    `,
    portalRoot,
  );
}

function JournalCompleted({ result, debug, meta }) {
  if (isIesReportPayload(result)) {
    const request = result.request || {};
    const summary = result.summary || {};
    const metadata = result.metadata || {};
    const scopeInfo = getIesReportScope(
      request.filter_type === "region"
        ? "region_specific"
        : request.filter_type === "global"
          ? "global"
          : "country_specific",
      request.filter_value || request.country || summary.filter_value || summary.country || "",
    );
    return html`
      <div className="atelier-panel-strong rounded-[22px] px-5 py-5 my-auto flex flex-col justify-center shadow-xs">
        <div className="flex flex-col items-center justify-center text-center gap-1.5">
          <p className="m-0 font-display text-[10px] font-medium uppercase tracking-[0.24em] text-atelier-moss/70">
            Report Summary
          </p>
          <h3 className="m-0 font-display text-xl md:text-2xl font-semibold leading-tight text-atelier-ink">
            Industry Earnings Snapshot
          </h3>
        </div>

        <div className="mt-4 grid gap-2.5 grid-cols-2">
          <${MetricCard} label="Industry" value=${request.industry || summary.industry || "N/A"} tone="accent" />
          <${MetricCard} label=${scopeInfo.scopeLabel} value=${scopeInfo.label} tone="gold" />
          <${MetricCard} label="Companies" value=${String(summary.companies_returned || result.companies?.length || 0)} />
          <${MetricCard} label="Enriched" value=${String(summary.companies_enriched ?? metadata.total_companies_successfully_enriched ?? 0)} />
        </div>

        <div className="editorial-rule mt-4"></div>

        <div className="mt-4 grid gap-2.5 grid-cols-2">
          <${MetricCard} label="Median Rev. Growth (LQ YoY)" value=${formatIesPercent(summary.median_revenue_growth)} />
          <${MetricCard} label="Median Op. Margin (TTM)" value=${formatIesPercent(summary.median_operating_margin)} />
          <${MetricCard} label="Median EBITDA Margin (TTM)" value=${formatIesPercent(summary.median_ebitda_margin)} />
          <${MetricCard} label="EV / Revenue" value=${formatIesRatio(summary.median_ev_to_revenue)} />
          <${MetricCard} label="EV / EBITDA" value=${formatIesRatio(summary.median_ev_to_ebitda)} />
          <${MetricCard} label="Forward P/E" value=${formatIesRatio(summary.median_forward_pe)} />
          <${MetricCard} label="EPS Beat Rate (LQ)" value=${formatIesPercent(summary.eps_beat_rate)} />
          <${MetricCard} label="5-Day Reaction" value=${formatIesPercent(summary.median_five_day_price_reaction)} />
        </div>
      </div>
    `;
  }

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

function formatIesPercent(value, fallback = "—") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(1)}%`;
}

function formatIesRatio(value, fallback = "—") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return `${numeric.toFixed(1)}x`;
}

function formatIesCompactNumber(value, fallback = "—") {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  const abs = Math.abs(numeric);
  if (abs >= 1_000_000_000_000) {
    return `$${(numeric / 1_000_000_000_000).toFixed(2)}T`;
  }
  if (abs >= 1_000_000_000) {
    return `$${(numeric / 1_000_000_000).toFixed(2)}B`;
  }
  if (abs >= 1_000_000) {
    return `$${(numeric / 1_000_000).toFixed(2)}M`;
  }
  if (abs >= 1_000) {
    return `$${(numeric / 1_000).toFixed(1)}K`;
  }
  return `$${numeric.toFixed(2)}`;
}

function renderIesMetricValue(formattedValue, rawValue) {
  if (formattedValue === "—" || formattedValue === "N/A") {
    return html`<span className="text-atelier-moss/40 font-display tabular-nums">—</span>`;
  }
  const numeric = Number(rawValue);
  if (Number.isFinite(numeric)) {
    if (numeric > 0) {
      return html`<span className="text-emerald-700 font-display tabular-nums font-semibold">${formattedValue}</span>`;
    }
    if (numeric < 0) {
      return html`<span className="text-rose-700 font-display tabular-nums font-semibold">${formattedValue}</span>`;
    }
  }
  return html`<span className="text-atelier-ink font-display tabular-nums font-semibold">${formattedValue}</span>`;
}

function IesScatterChart({ chart }) {
  const stageRef = useRef(null);
  const tooltipRef = useRef(null);
  const [activeTicker, setActiveTicker] = useState("");
  const [selectedTicker, setSelectedTicker] = useState("");
  const [tooltipState, setTooltipState] = useState({
    visible: false,
    x: 0,
    y: 0,
    title: "",
    ticker: "",
    country: "",
    fields: [],
  });

  const points = Array.isArray(chart?.data) ? chart.data.filter(Boolean) : [];
  const normalizedPoints = points
    .map((point, index) => ({
      ...point,
      index,
      x: Number(point.revenue_growth_lq_yoy),
      y: Number(point.operating_margin),
      bubble: Number(point.bubble_size),
      ticker: String(point.ticker || "").trim(),
      company_name: String(point.company_name || "").trim(),
      country: String(point.country || point.exchange || "").trim(),
      is_outlier: Boolean(point.is_outlier),
    }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));

  const hasData = normalizedPoints.length > 0;

  const xValues = normalizedPoints.map((point) => point.x);
  const yValues = normalizedPoints.map((point) => point.y);
  const bubbleValues = normalizedPoints
    .map((point) => (Number.isFinite(point.bubble) ? point.bubble : null))
    .filter((value) => value !== null);
  const xMedian = hasData ? medianOfValues(xValues) : 0;
  const yMedian = hasData ? medianOfValues(yValues) : 0;
  const xMin = hasData ? Math.min(...xValues) : 0;
  const xMax = hasData ? Math.max(...xValues) : 1;
  const yMin = hasData ? Math.min(...yValues) : 0;
  const yMax = hasData ? Math.max(...yValues) : 1;
  const bubbleMin = bubbleValues.length ? Math.min(...bubbleValues) : 1;
  const bubbleMax = bubbleValues.length ? Math.max(...bubbleValues) : 1;
  const pointLookup = normalizedPoints.reduce((acc, point) => {
    acc[point.ticker || point.company_name || String(point.index)] = point;
    return acc;
  }, {});
  const chartTitle = "Peer Positioning";
  const xLabel = String(chart?.x_label || "Revenue Growth (LQ YoY)").trim();
  const yLabel = "Operating Margin (TTM)";
  const bubbleLabel = String(chart?.bubble_size_label || "Revenue TTM").trim();

  function getPointKey(point) {
    return point.ticker || point.company_name || String(point.index);
  }

  function getPointRadius(point) {
    const normalizedBubble = Number.isFinite(point.bubble) ? point.bubble : bubbleMin;
    const bubbleRange = Math.max(1, bubbleMax - bubbleMin);
    const scaled = 9 + ((normalizedBubble - bubbleMin) / bubbleRange) * 20;
    return clamp(scaled, 9, 29);
  }

  function getPlotFrame() {
    const width = 1000;
    const height = 560;
    const margin = {
      top: 42,
      right: 48,
      bottom: 76,
      left: 104,
    };
    const plotWidth = Math.max(0, width - margin.left - margin.right);
    const plotHeight = Math.max(0, height - margin.top - margin.bottom);
    return { width, height, margin, plotWidth, plotHeight };
  }

  function xScale(value) {
    const { margin, plotWidth } = getPlotFrame();
    const min = xMin - (xMax - xMin || 1) * 0.18;
    const max = xMax + (xMax - xMin || 1) * 0.18;
    return margin.left + ((value - min) / Math.max(1, max - min)) * plotWidth;
  }

  function yScale(value) {
    const { margin, plotHeight } = getPlotFrame();
    const min = yMin - (yMax - yMin || 1) * 0.18;
    const max = yMax + (yMax - yMin || 1) * 0.18;
    return margin.top + plotHeight - ((value - min) / Math.max(1, max - min)) * plotHeight;
  }

  function getBubbleGradientId(value) {
    if (!Number.isFinite(value)) {
      return "url(#ies-grad-neu)";
    }
    const pivot = yMedian || 0;
    const spread = Math.max(4, Math.abs(yMax - yMin) * 0.4);
    const diff = value - pivot;
    if (diff > spread * 0.08) {
      return "url(#ies-grad-pos)";
    }
    if (diff < -spread * 0.08) {
      return "url(#ies-grad-neg)";
    }
    return "url(#ies-grad-neu)";
  }

  function formatAxisPercent(value) {
    if (!Number.isFinite(value)) {
      return "—";
    }
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(1)}%`;
  }

  function buildTooltipFields(point) {
    return [
      { label: "Revenue TTM", value: formatIesCompactNumber(point.bubble) },
      { label: "Revenue Growth", value: formatIesPercent(point.x) },
      { label: "Operating Margin", value: formatIesPercent(point.y) },
      { label: "Reported EPS", value: Number.isFinite(point.reported_eps) ? `$${point.reported_eps.toFixed(2)}` : "—" },
      { label: "EPS Surprise", value: formatIesPercent(point.eps_surprise) },
      { label: "Forward P/E", value: formatIesRatio(point.forward_pe) },
      { label: "5-Day Reaction", value: formatIesPercent(point.five_day_price_reaction) },
    ];
  }

  function showTooltipForPoint(point, event) {
    if (!point) {
      return;
    }
    const container = stageRef.current;
    if (!container) {
      return;
    }
    const rect = container.getBoundingClientRect();
    const pointerX = event && Number.isFinite(event.clientX) ? event.clientX - rect.left : (xScale(point.x) / 1000) * rect.width;
    const pointerY = event && Number.isFinite(event.clientY) ? event.clientY - rect.top : (yScale(point.y) / 560) * rect.height;
    setTooltipState({
      visible: true,
      x: clamp(pointerX, 16, rect.width - 16),
      y: clamp(pointerY, 16, rect.height - 16),
      title: point.company_name || point.ticker || "Company",
      ticker: point.ticker || "",
      country: point.country || point.exchange || "",
      fields: buildTooltipFields(point),
    });
  }

  function hideTooltipIfNeeded(point) {
    if (activeTicker === getPointKey(point)) {
      setActiveTicker("");
    }
    setTooltipState((current) => ({ ...current, visible: false }));
  }

  function handleEnter(point, event) {
    const key = getPointKey(point);
    setActiveTicker(key);
    showTooltipForPoint(point, event);
  }

  function handleMove(point, event) {
    showTooltipForPoint(point, event);
  }

  function handleLeave(point) {
    const key = getPointKey(point);
    if (activeTicker === key) {
      setActiveTicker("");
    }
    setTooltipState((current) => ({ ...current, visible: false }));
  }

  function handleStagePointerLeave() {
    setActiveTicker("");
    setTooltipState((current) => ({ ...current, visible: false }));
  }

  function handleStageClick(event) {
    if (event.target.tagName === "svg" || event.target.classList.contains("ies-chart-stage") || event.target.tagName === "rect" || event.target.tagName === "line") {
      setSelectedTicker("");
      setActiveTicker("");
      setTooltipState((current) => ({ ...current, visible: false }));
    }
  }

  function handleSelect(point, event) {
    event.stopPropagation();
    const key = getPointKey(point);
    const nextSelected = selectedTicker === key ? "" : key;
    setSelectedTicker(nextSelected);
    if (nextSelected) {
      showTooltipForPoint(point, event);
    } else {
      setTooltipState((current) => ({ ...current, visible: false }));
    }
  }

  useEffect(() => {
    function handleResize() {
      const point = pointLookup[selectedTicker] || pointLookup[activeTicker];
      if (point) {
        setTooltipState((current) => ({
          ...current,
          x: xScale(point.x),
          y: yScale(point.y),
        }));
      }
    }

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [activeTicker, selectedTicker, chart?.title]);

  if (!hasData) {
    return html`
      <div className="rounded-[24px] border border-dashed border-atelier-line/80 bg-white/70 px-6 py-8 text-center text-sm leading-7 text-atelier-moss">
        No scatter chart data was returned for this report.
      </div>
    `;
  }

  const { width, height, margin, plotWidth, plotHeight } = getPlotFrame();
  const axisXMin = xMin - (xMax - xMin || 1) * 0.18;
  const axisXMax = xMax + (xMax - xMin || 1) * 0.18;
  const axisYMin = yMin - (yMax - yMin || 1) * 0.18;
  const axisYMax = yMax + (yMax - yMin || 1) * 0.18;
  const gridLineCount = 4;
  const xTicks = Array.from({ length: gridLineCount + 1 }, (_, index) => axisXMin + ((axisXMax - axisXMin) * index) / gridLineCount);
  const yTicks = Array.from({ length: gridLineCount + 1 }, (_, index) => axisYMin + ((axisYMax - axisYMin) * index) / gridLineCount);
  const leftAxisX = margin.left;
  const rightAxisX = margin.left + plotWidth;
  const topAxisY = margin.top;
  const bottomAxisY = margin.top + plotHeight;
  const medianX = xScale(xMedian);
  const medianY = yScale(yMedian);

  const sortedPoints = [...normalizedPoints].sort((a, b) => {
    const aActive = activeTicker === getPointKey(a) || selectedTicker === getPointKey(a);
    const bActive = activeTicker === getPointKey(b) || selectedTicker === getPointKey(b);
    if (aActive && !bActive) return 1;
    if (!aActive && bActive) return -1;
    return b.bubble - a.bubble;
  });

  return html`
    <div className="rounded-[28px] border border-atelier-line/80 bg-white/80 p-5 md:p-7 shadow-[0_20px_50px_rgba(31,42,41,0.05)]">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-atelier-line/60 pb-4">
        <div>
          <h4 className="m-0 font-display text-2xl md:text-3xl font-semibold leading-tight text-atelier-ink">
            Peer Positioning
          </h4>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="inline-flex items-center gap-2 rounded-full border border-atelier-line/80 bg-white/90 px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-atelier-ink shadow-2xs">
            <span className="h-2 w-2 rounded-full bg-amber-600"></span>
            <span>Bubble Size: <strong className="text-atelier-forest">${bubbleLabel}</strong></span>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-atelier-line/80 bg-white/90 px-3.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-atelier-ink shadow-2xs">
            <div className="flex h-2.5 w-6 rounded-full bg-gradient-to-r from-[#D96B60] via-[#C5BEB5] to-[#4E8764]"></div>
            <span>Color: <strong className="text-atelier-forest">${yLabel}</strong></span>
          </div>
          <div className="group relative inline-flex items-center gap-1.5 rounded-full bg-atelier-forest/8 px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-atelier-forest cursor-help">
            <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span>View Details</span>
            <div className="pointer-events-none absolute right-0 top-full mt-2 hidden w-72 rounded-xl border border-atelier-line/90 bg-[#1F2A29] p-3 text-xs normal-case leading-relaxed font-normal text-white shadow-xl group-hover:block z-40">
              The chart compares latest-quarter year-on-year revenue growth with TTM operating margins, showing how each peer balances current growth momentum with underlying profitability.
            </div>
          </div>
        </div>
      </div>

      <div
        ref=${stageRef}
        className="ies-chart-stage mt-6 rounded-[24px] border border-atelier-line/60 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-[#FFFDF8] via-white to-[#F9F5EC] p-4 md:p-6 shadow-[inset_0_1px_2px_rgba(255,255,255,0.9),0_20px_50px_rgba(31,42,41,0.04)]"
        style=${{
      position: "relative",
      overflow: "visible",
      minHeight: "35rem",
    }}
        onPointerLeave=${handleStagePointerLeave}
        onClick=${handleStageClick}
      >
        <svg viewBox=${`0 0 ${width} ${height}`} className="ies-scatter block h-auto w-full overflow-visible">
          <defs>
            <radialGradient id="ies-grad-pos" cx="35%" cy="35%" r="65%">
              <stop offset="0%" stopColor="#6EA383" stopOpacity="0.95" />
              <stop offset="70%" stopColor="#4E8764" stopOpacity="0.88" />
              <stop offset="100%" stopColor="#3A6A4E" stopOpacity="0.9" />
            </radialGradient>
            <radialGradient id="ies-grad-neu" cx="35%" cy="35%" r="65%">
              <stop offset="0%" stopColor="#DCD5CC" stopOpacity="0.95" />
              <stop offset="70%" stopColor="#C5BEB5" stopOpacity="0.88" />
              <stop offset="100%" stopColor="#A8A096" stopOpacity="0.9" />
            </radialGradient>
            <radialGradient id="ies-grad-neg" cx="35%" cy="35%" r="65%">
              <stop offset="0%" stopColor="#E88B81" stopOpacity="0.95" />
              <stop offset="70%" stopColor="#D96B60" stopOpacity="0.88" />
              <stop offset="100%" stopColor="#B84F45" stopOpacity="0.9" />
            </radialGradient>
            <filter id="ies-bubble-shadow" x="-40%" y="-40%" width="180%" height="180%">
              <feDropShadow dx="0" dy="5" stdDeviation="4" flood-color="#1F2A29" flood-opacity="0.15" />
            </filter>
            <filter id="ies-bubble-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feDropShadow dx="0" dy="0" stdDeviation="7" flood-color="#27433C" flood-opacity="0.3" />
            </filter>
          </defs>

          <!-- Watermark Quadrant Labels -->
          <g className="quadrant-watermarks pointer-events-none select-none">
            <text x=${leftAxisX + plotWidth * 0.75} y=${topAxisY + plotHeight * 0.22} textAnchor="middle" fontSize="11" fontWeight="700" letterSpacing="0.22em" fill="rgba(65,80,74,0.07)">HIGH GROWTH • HIGH MARGIN</text>
            <text x=${leftAxisX + plotWidth * 0.25} y=${topAxisY + plotHeight * 0.22} textAnchor="middle" fontSize="11" fontWeight="700" letterSpacing="0.22em" fill="rgba(65,80,74,0.07)">LOW GROWTH • HIGH MARGIN</text>
            <text x=${leftAxisX + plotWidth * 0.75} y=${topAxisY + plotHeight * 0.78} textAnchor="middle" fontSize="11" fontWeight="700" letterSpacing="0.22em" fill="rgba(65,80,74,0.07)">HIGH GROWTH • LOW MARGIN</text>
            <text x=${leftAxisX + plotWidth * 0.25} y=${topAxisY + plotHeight * 0.78} textAnchor="middle" fontSize="11" fontWeight="700" letterSpacing="0.22em" fill="rgba(65,80,74,0.07)">LOW GROWTH • LOW MARGIN</text>
          </g>

          <!-- Grid Lines -->
          ${yTicks.map((tick, index) => {
      const y = topAxisY + plotHeight - ((tick - axisYMin) / Math.max(1, axisYMax - axisYMin)) * plotHeight;
      return html`
              <g key=${`y-grid-${index}`}>
                <line x1=${leftAxisX} y1=${y} x2=${rightAxisX} y2=${y} stroke="rgba(104,117,113,0.06)" strokeWidth="0.8" />
                <text x=${leftAxisX - 14} y=${y + 4} textAnchor="end" fontSize="11" fontFamily="Manrope, sans-serif" fontWeight="600" fill="#65706A">
                  ${formatAxisPercent(tick)}
                </text>
              </g>
            `;
    })}

          ${xTicks.map((tick, index) => {
      const x = leftAxisX + ((tick - axisXMin) / Math.max(1, axisXMax - axisXMin)) * plotWidth;
      return html`
              <g key=${`x-grid-${index}`}>
                <line x1=${x} y1=${topAxisY} x2=${x} y2=${bottomAxisY} stroke="rgba(104,117,113,0.06)" strokeWidth="0.8" />
                <text x=${x} y=${bottomAxisY + 20} textAnchor="middle" fontSize="11" fontFamily="Manrope, sans-serif" fontWeight="600" fill="#65706A">
                  ${formatAxisPercent(tick)}
                </text>
              </g>
            `;
    })}

          <!-- Median Lines -->
          <line x1=${leftAxisX} y1=${medianY} x2=${rightAxisX} y2=${medianY} stroke="rgba(88,104,101,0.25)" strokeWidth="1.2" strokeDasharray="5 5" />
          <line x1=${medianX} y1=${topAxisY} x2=${medianX} y2=${bottomAxisY} stroke="rgba(88,104,101,0.25)" strokeWidth="1.2" strokeDasharray="5 5" />

          <!-- Median Labels -->
          <g className="median-labels pointer-events-none select-none">
            <text x=${rightAxisX - 10} y=${medianY - 6} textAnchor="end" fontSize="9" fontWeight="700" letterSpacing="0.16em" fill="rgba(88,104,101,0.45)">ABOVE MEDIAN MARGIN</text>
            <text x=${rightAxisX - 10} y=${medianY + 14} textAnchor="end" fontSize="9" fontWeight="700" letterSpacing="0.16em" fill="rgba(88,104,101,0.45)">BELOW MEDIAN MARGIN</text>
            <text x=${medianX + 8} y=${topAxisY + 14} textAnchor="start" fontSize="9" fontWeight="700" letterSpacing="0.16em" fill="rgba(88,104,101,0.45)">ABOVE MEDIAN GROWTH</text>
            <text x=${medianX - 8} y=${topAxisY + 14} textAnchor="end" fontSize="9" fontWeight="700" letterSpacing="0.16em" fill="rgba(88,104,101,0.45)">BELOW MEDIAN GROWTH</text>
          </g>

          <!-- Axes Bounding Lines -->
          <line x1=${leftAxisX} y1=${bottomAxisY} x2=${rightAxisX} y2=${bottomAxisY} stroke="rgba(31,42,41,0.22)" strokeWidth="1.2" />
          <line x1=${leftAxisX} y1=${topAxisY} x2=${leftAxisX} y2=${bottomAxisY} stroke="rgba(31,42,41,0.22)" strokeWidth="1.2" />

          <!-- Bubbles -->
          ${sortedPoints.map((point) => {
      const pointKey = getPointKey(point);
      const isActive = activeTicker === pointKey;
      const isSelected = selectedTicker === pointKey;
      const showLabel = isActive || isSelected;
      const x = xScale(point.x);
      const y = yScale(point.y);
      const radius = getPointRadius(point);
      const displayRadius = isActive || isSelected ? radius * 1.15 : radius;
      const opacity = isActive || isSelected ? 1 : 0.86;
      const bubbleFill = getBubbleGradientId(point.y);
      const labelY = y - (isActive || isSelected ? 12 : 10);
      const labelAnchor = x > width * 0.64 ? "end" : "start";
      const labelOffset = x > width * 0.64 ? -12 : 12;

      return html`
              <g
                key=${pointKey}
                className="ies-scatter-point-group outline-none focus:outline-none focus-visible:outline-none focus:ring-0"
                style=${{ outline: "none", boxShadow: "none" }}
                data-state=${isSelected ? "selected" : isActive ? "active" : "idle"}
                transform=${`translate(${x}, ${y})`}
                onPointerEnter=${(event) => handleEnter(point, event)}
                onPointerMove=${(event) => handleMove(point, event)}
                onPointerLeave=${() => handleLeave(point)}
                onFocus=${(event) => handleEnter(point, event)}
                onBlur=${() => handleLeave(point)}
                onClick=${(event) => handleSelect(point, event)}
                role="button"
                tabIndex="0"
              >
                ${isSelected
          ? html`
                      <circle
                        r=${displayRadius + 6}
                        fill="none"
                        stroke="#27433C"
                        strokeWidth="1.8"
                        strokeDasharray="4 3"
                        className="animate-spin-slow"
                      />
                    `
          : null}
                <circle
                  className="ies-scatter-point outline-none focus:outline-none"
                  r=${displayRadius}
                  fill=${bubbleFill}
                  fillOpacity=${opacity}
                  stroke="#FFFFFF"
                  strokeWidth="2"
                  filter=${isActive || isSelected ? "url(#ies-bubble-glow)" : "url(#ies-bubble-shadow)"}
                  style=${{
          outline: "none",
          boxShadow: "none",
          transition: "transform 200ms ease-out, r 200ms ease-out, opacity 200ms ease-out",
        }}
                />
              </g>
            `;
    })}

          <!-- Axis Titles -->
          <text x=${(leftAxisX + rightAxisX) / 2} y=${height - 4} textAnchor="middle" fontSize="12" fontWeight="700" fill="#41504A">
            ${xLabel}
          </text>
          <text
            x="18"
            y=${(topAxisY + bottomAxisY) / 2}
            textAnchor="middle"
            fontSize="12"
            fontWeight="700"
            fill="#41504A"
            transform=${`rotate(-90 18 ${(topAxisY + bottomAxisY) / 2})`}
          >
            ${yLabel}
          </text>
        </svg>

        <!-- Redesigned Executive Floating Glass Tooltip -->
        <div
          ref=${tooltipRef}
          className=${cx(
      "ies-scatter-tooltip pointer-events-none absolute z-30 transition-all duration-75 ease-out",
      tooltipState.visible ? "opacity-100 scale-100 translate-y-0" : "opacity-0 scale-95 translate-y-2 pointer-events-none"
    )}
          aria-hidden=${tooltipState.visible ? "false" : "true"}
          style=${{
      left: `${tooltipState.x}px`,
      top: `${tooltipState.y}px`,
      transform: "translate(-50%, -100%) translateY(-14px)",
    }}
        >
          <div className="w-[19rem] md:w-[22rem] rounded-2xl border border-atelier-line/80 bg-[#FFFDF9]/62 p-4 shadow-[0_24px_50px_rgba(31,42,41,0.15)] backdrop-blur-xl">
            <div className="flex items-center justify-between gap-3 border-b border-atelier-line/50 pb-3">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-atelier-forest/10 font-mono text-xs font-bold text-atelier-forest">
                  ${(tooltipState.ticker || tooltipState.title || "CO").slice(0, 3).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <h5 className="m-0 truncate font-display text-sm font-bold text-atelier-ink">
                    ${tooltipState.title}
                  </h5>
                  <div className="mt-0.5 flex flex-wrap gap-1.5">
                    ${tooltipState.ticker ? html`<span className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-atelier-moss uppercase">${tooltipState.ticker}</span>` : null}
                    ${tooltipState.country ? html`<span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-900/80">${tooltipState.country}</span>` : null}
                  </div>
                </div>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
              ${tooltipState.fields.map(
      (field) => html`
                  <div key=${field.label} className="flex flex-col min-w-0">
                    <span className="text-[9px] font-bold uppercase tracking-[0.16em] text-atelier-moss/65">${field.label}</span>
                    <span className="mt-0.5 text-xs font-mono font-semibold text-atelier-ink truncate">
                      ${field.value}
                    </span>
                  </div>
                `,
    )}
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function medianOfValues(values) {
  const numericValues = Array.isArray(values)
    ? values.map((value) => Number(value)).filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
    : [];
  if (!numericValues.length) {
    return 0;
  }
  const middle = Math.floor(numericValues.length / 2);
  if (numericValues.length % 2) {
    return numericValues[middle];
  }
  return (numericValues[middle - 1] + numericValues[middle]) / 2;
}

function IesCompanyRow({ company, index, selected, onSelect }) {
  const companyName = company.company_name || company.ticker || "Company";
  const isDcmRow = String(company.ticker || "").toUpperCase() === "DCM.VN";
  const contentSizeClass = isDcmRow ? "text-[11px] sm:text-[12px]" : "text-xs sm:text-sm";
  const metricSizeClass = isDcmRow ? "text-[11px] sm:text-[12px]" : "text-xs sm:text-sm";

  return html`
    <tr
      className=${cx(
    "ies-universe-row group cursor-pointer transition-colors duration-75",
    index % 2 === 1 ? "bg-white/40" : "bg-[#FAF7F2]/30",
    company.is_outlier ? "bg-amber-50/40" : "",
    selected ? "bg-amber-100/60 shadow-xs border-l-4 border-l-atelier-gold" : "hover:bg-[#F5EFE6]/80"
  )}
      onClick=${onSelect}
      role="button"
      tabIndex="0"
      aria-selected=${selected ? "true" : "false"}
      onKeyDown=${(event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect(event);
      }
    }}
    >
      <td className="py-3 pl-3 pr-1 font-display text-xs font-semibold text-atelier-moss/60 align-middle text-center w-8">
        ${String(index + 1).padStart(2, "0")}
      </td>
      <td className="py-3 px-2.5 align-middle">
        <div className="flex flex-col min-w-0">
          <span className=${cx("font-display font-bold text-atelier-ink group-hover:text-atelier-forest transition-colors break-words whitespace-normal leading-tight", contentSizeClass)}>
            ${companyName}
          </span>
          <div className=${cx("flex flex-wrap items-center gap-1 mt-0.5 text-atelier-moss/80 font-display", isDcmRow ? "text-[9px] sm:text-[10px]" : "text-[10px]")}>
            <span className="font-semibold text-atelier-ink">${company.ticker || "—"}</span>
            ${company.exchange ? html`<span>• ${company.exchange}</span>` : null}
            ${company.country ? html`<span>• ${company.country}</span>` : null}
          </div>
        </div>
      </td>
      <td className=${cx("py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle", metricSizeClass)}>
        ${formatIesCompactNumber(company.revenue_ttm, "—")}
      </td>
      <td className=${cx("py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle", metricSizeClass)}>
        ${renderIesMetricValue(formatIesPercent(company.revenue_growth_lq_yoy, "—"), company.revenue_growth_lq_yoy)}
      </td>
      <td className=${cx("py-3 px-2 text-center font-display tabular-nums font-semibold text-atelier-ink align-middle", metricSizeClass)}>
        ${renderIesMetricValue(formatIesPercent(company.operating_margin, "—"), company.operating_margin)}
      </td>
      <td className=${cx("py-3 px-2 text-center font-display tabular-nums font-medium text-atelier-ink align-middle", metricSizeClass)}>
        ${formatIesRatio(company.ev_to_revenue_ttm, "—")}
      </td>
      <td className=${cx("py-3 px-2 text-center font-display tabular-nums font-medium text-atelier-ink align-middle", metricSizeClass)}>
        ${formatIesRatio(company.ev_to_ebitda_ttm, "—")}
      </td>
    </tr>
  `;
}
function IesAnalystInsights({ result }) {
  const insightBundle = buildIesInsightRows(result);

  return html`
    <section className="ies-insights-shell rounded-[28px] border border-atelier-line/80 bg-white/80 p-6 md:p-8 shadow-[0_20px_50px_rgba(31,42,41,0.04)]">
      <div className="flex flex-col gap-1.5">
        <h4 className="m-0 font-display text-2xl md:text-3xl font-semibold leading-tight text-atelier-ink">
          Editorial Readout & Market Structure
        </h4>
        <p className="mt-1 font-display text-xs md:text-sm font-medium leading-relaxed text-atelier-moss">
          ${insightBundle.summary}
        </p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        ${insightBundle.rows.map(
    (row, index) => html`
            <${motion.div}
              key=${`${row.label}-${index}`}
              initial=${{ opacity: 0, y: 10 }}
              animate=${{ opacity: 1, y: 0 }}
              transition=${{ ...TRANSITION, delay: index * 0.05 }}
              style=${MOTION_SMOOTH_STYLE}
            >
              <${IesInsightCard} label=${row.label} body=${row.body} tone=${row.tone} icon=${row.icon} />
            </${motion.div}>
          `,
  )}
      </div>
    </section>
  `;
}

function IesInsightCard({ label, body, tone = "default", icon }) {
  const borderToneClass =
    tone === "accent"
      ? "border-l-emerald-600 bg-gradient-to-br from-emerald-50/25 to-white/90"
      : tone === "gold"
        ? "border-l-amber-600 bg-gradient-to-br from-amber-50/25 to-white/90"
        : tone === "forest"
          ? "border-l-atelier-forest bg-gradient-to-br from-stone-50/40 to-white/90"
          : tone === "outlier"
            ? "border-l-amber-500 bg-gradient-to-br from-orange-50/25 to-white/90"
            : "border-l-slate-500 bg-gradient-to-br from-slate-50/25 to-white/90";

  return html`
    <div className=${cx("ies-insight-card h-full rounded-2xl border border-atelier-line/70 border-l-4 p-5 shadow-2xs hover:shadow-md transition-all duration-200", borderToneClass)}>
      <div className="flex items-center gap-2">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/80 shadow-2xs">
          ${icon || html`<svg className="w-4 h-4 text-atelier-forest" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/></svg>`}
        </div>
        <p className="m-0 font-display text-[12px] font-semibold text-atelier-ink">
          ${label}
        </p>
      </div>
      <p className="mt-2.5 font-display text-xs md:text-sm leading-relaxed text-atelier-moss font-medium whitespace-pre-line">
        ${body}
      </p>
    </div>
  `;
}

function IesCompanyUniverseTable({ companies, selectedCompanyKey, onSelectCompany }) {
  const normalizedCompanies = Array.isArray(companies) ? companies.filter(Boolean) : [];

  if (!normalizedCompanies.length) {
    return html`
      <div className="rounded-[24px] border border-dashed border-atelier-line/80 bg-white/70 px-6 py-8 text-center text-sm leading-7 text-atelier-moss">
        No companies were returned for this report.
      </div>
    `;
  }

  return html`
    <div className="overflow-hidden rounded-2xl border border-atelier-line/80 bg-white/80 shadow-[0_18px_48px_rgba(31,42,41,0.04)]" style=${{ contain: "content" }}>
      <div className="max-h-[38rem] overflow-y-auto panel-scroll">
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 z-20 isolate bg-[#FAF6F0] border-b border-atelier-line/80">
            <tr>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 pl-3 pr-1 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70 w-8">#</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2.5 text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Company & Ticker</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Revenue (TTM)</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Rev. Growth (LQ YoY)</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">Op. Margin (TTM)</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">EV / Revenue</th>
              <th className="sticky top-0 z-20 bg-[#FAF6F0] py-3 px-2 text-center text-[10px] font-bold uppercase tracking-[0.18em] text-atelier-moss/70">EV / EBITDA</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-atelier-line/40">
            ${normalizedCompanies.map(
    (company, index) => html`
                <${IesCompanyRow}
                  key=${`${getIesDisplayCompanyKey(company, index)}-${index}`}
                  company=${company}
                  index=${index}
                  selected=${selectedCompanyKey === getIesDisplayCompanyKey(company, index)}
                  onSelect=${() => onSelectCompany(getIesDisplayCompanyKey(company, index))}
                />
              `,
  )}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function IesResultSection({ result, meta, onDownload, exportPending }) {
  const request = result?.request || {};
  const summary = result?.summary || {};
  const companies = Array.isArray(result?.companies) ? result.companies : [];
  const chart = result?.scatter_chart || {};
  const metadata = result?.metadata || {};
  const topN = request.top_n || summary.requested_top_n || companies.length || 0;
  const [selectedCompanyKey, setSelectedCompanyKey] = useState("");
  const selectedCompany = companies.find((company, index) => getIesDisplayCompanyKey(company, index) === selectedCompanyKey) || null;
  const displayIndustry = request.industry || summary.industry || "Industry";
  const displayScope = request.filter_type || summary.filter_type || "country";
  const displayScopeValue =
    request.filter_value ||
    summary.filter_value ||
    request.country ||
    summary.country ||
    meta?.location?.label ||
    "Global";
  const preparedDate = formatDate();
  const coverageLabel = `Top ${topN || 0} Companies`;
  const scopeLabel = displayScope === "region" ? "Region" : displayScope === "global" ? "Scope" : "Country";
  const scopeValue = displayScope === "global" ? "Global" : displayScopeValue;

  const executiveMetrics = [
    { label: "Companies Scanned", value: String(summary.companies_returned || companies.length || 0) },
    { label: "Companies Fetched", value: String(summary.companies_enriched ?? 0) },
    { label: "Median Rev. Growth (LQ YoY)", value: formatIesPercent(summary.median_revenue_growth), trend: Number(summary.median_revenue_growth) > 0 ? "up" : Number(summary.median_revenue_growth) < 0 ? "down" : null },
    { label: "Median Op. Margin (TTM)", value: formatIesPercent(summary.median_operating_margin), trend: Number(summary.median_operating_margin) > 0 ? "up" : Number(summary.median_operating_margin) < 0 ? "down" : null },
    { label: "Median EV / Revenue", value: formatIesRatio(summary.median_ev_to_revenue) },
    { label: "Median EV / EBITDA", value: formatIesRatio(summary.median_ev_to_ebitda) },
  ];

  useEffect(() => {
    setSelectedCompanyKey("");
  }, [result?.title]);

  return html`
    <div className="paper-sheet ies-result-sheet flex w-full flex-col rounded-[32px] px-6 py-6 md:px-10 md:py-10 space-y-9 my-auto justify-center">
      <!-- 1. Industry Header -->
      <section className="ies-hero">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="w-full space-y-2">
            <h3 className="font-display text-4xl sm:text-5xl font-semibold leading-[0.95] tracking-tight text-atelier-ink">
              ${result?.title || "Industry Earnings Snapshot"}
            </h3>
          </div>

          <div className="flex flex-col items-start gap-2.5 lg:items-end shrink-0">
            <${DownloadResultsButton} onClick=${onDownload} exporting=${exportPending} disabled=${exportPending} />
          </div>
        </div>

      </section>

      <!-- 2. Executive KPI Strip (Horizontal Ribbon) -->
      <section>
        <div className="rounded-2xl border border-atelier-line/80 bg-white/75 backdrop-blur-md shadow-sm p-3 md:p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 divide-y sm:divide-y-0 sm:divide-x divide-atelier-line/50">
          ${executiveMetrics.map(
    (metric) => html`
              <div key=${metric.label} className="p-3 md:px-5 md:py-2 flex flex-col justify-center">
                <span className="font-display text-[8px] md:text-[9px] font-medium uppercase tracking-[0.14em] text-atelier-moss/70">
                  ${metric.label}
                </span>
                <div className="mt-1.5 flex items-baseline gap-2">
                  <span className="font-display text-2xl md:text-3xl font-semibold tracking-tight text-atelier-ink">
                    ${metric.value}
                  </span>
                  ${metric.trend === "up"
        ? html`<span className="text-xs font-bold text-emerald-700">↑</span>`
        : metric.trend === "down"
          ? html`<span className="text-xs font-bold text-rose-700">↓</span>`
          : null}
                </div>
              </div>
            `,
  )}
        </div>
      </section>

      <!-- 3. Interactive Scatter Visualization (Hero Component) -->
      <section>
        <${IesScatterChart} chart=${chart} />
      </section>

      <!-- 4. Insight Cards (Executive Insight Tiles) -->
      <section>
        <${IesAnalystInsights} result=${result} />
      </section>

      <!-- 5. Company Ranking Table -->
      <section>
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <div>
            <h4 className="m-0 font-display text-2xl font-semibold leading-tight text-atelier-ink">
              Company Ranking Table
            </h4>
          </div>
        </div>

        <${IesCompanyUniverseTable}
          companies=${companies}
          selectedCompanyKey=${selectedCompanyKey}
          onSelectCompany=${(key) => setSelectedCompanyKey((current) => (current === key ? "" : key))}
        />
      </section>

      <${IesCompanyDrawer}
        company=${selectedCompany}
        open=${Boolean(selectedCompany)}
        onClose=${() => setSelectedCompanyKey("")}
      />
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
      <div className="workspace-pane-body my-auto min-h-0 flex-1 flex flex-col justify-center overflow-hidden">
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

function CompetitiveLandscapeGroupTabs({ title, majorPlayers = [], emergingPlayers = [] }) {
  const [activeTab, setActiveTab] = useState("major_players");
  const tabs = [
    { id: "major_players", label: "Key Players", items: Array.isArray(majorPlayers) ? majorPlayers : [] },
    { id: "emerging_players", label: "Other Players", items: Array.isArray(emergingPlayers) ? emergingPlayers : [] },
  ];
  const activeGroup = tabs.find((tab) => tab.id === activeTab) || tabs[0];

  return html`
    <div className="mt-6 space-y-5">
      <div className="flex flex-wrap gap-3">
        ${tabs.map(
    (tab) => html`
            <button
              key=${tab.id}
              type="button"
              onClick=${() => setActiveTab(tab.id)}
              className=${cx(
      "rounded-full border px-4 py-2 text-xs font-bold uppercase tracking-[0.2em] transition-colors duration-200",
      activeGroup.id === tab.id
        ? "border-atelier-forest bg-atelier-forest text-white"
        : "border-atelier-line bg-white/80 text-atelier-moss hover:border-atelier-forest/30",
    )}
            >
              ${`${tab.label} (${tab.items.length})`}
            </button>
          `,
  )}
      </div>

      <div className="rounded-[24px] border border-atelier-line bg-white/54 px-4 py-4 md:px-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-moss/70">
            ${activeGroup.label}
          </p>
          <p className="m-0 text-[11px] font-bold uppercase tracking-[0.18em] text-atelier-moss/55">
            ${`${activeGroup.items.length} companies`}
          </p>
        </div>

        <div className="space-y-4">
          ${activeGroup.items.length
      ? activeGroup.items.map(
        (item, index) => html`
                  <${BriefItemCard}
                    item=${item}
                    index=${index}
                    section="competitive_landscape"
                    title=${`${title}-${activeGroup.id}`}
                  />
                `,
      )
      : html`
                <div className="rounded-[26px] border border-dashed border-atelier-line bg-white/76 px-5 py-6 text-sm leading-8 text-atelier-moss">
                  No strong company profiles found.
                </div>
              `}
        </div>
      </div>
    </div>
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
            ${item.market_role
        ? html`
                  <p className="m-0 text-[11px] font-bold uppercase tracking-[0.22em] text-atelier-goldDeep">
                    ${item.market_role}
                  </p>
                `
        : null}
            <h4 className="mt-3 font-display text-[2rem] font-semibold leading-[1.02] text-atelier-ink">
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
  majorPlayers = [],
  emergingPlayers = [],
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

      ${section === "competitive_landscape"
      ? html`
            <${CompetitiveLandscapeGroupTabs}
              title=${title}
              majorPlayers=${majorPlayers}
              emergingPlayers=${emergingPlayers}
            />
          `
      : html`
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
          `}
    </div>
  `;
}

function BriefCompleted({
  result,
  debug,
  meta,
  onDownload,
  exportPending,
  followUpEnabled,
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
  const isIesReport = isIesReportPayload(result);
  return html`
    <div className="flex w-full justify-center">
      <div className="flex w-full flex-col gap-5">
        ${isIesReport
      ? html`<${IesResultSection} result=${result} meta=${meta} onDownload=${onDownload} exportPending=${exportPending} />`
      : html`<${ResultSection}
              title=${result.title || sectionTitle(result.section)}
              section=${result.section}
              items=${result.items}
              majorPlayers=${result.major_players}
              emergingPlayers=${result.emerging_players}
              meta=${meta}
              debug=${debug}
              aside=${html`<${DownloadResultsButton} onClick=${onDownload} exporting=${exportPending} disabled=${exportPending} />`}
            />`}

        ${followUpEnabled && !isIesReport
      ? html`
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
            `
      : null}

        ${followUpEnabled && !isIesReport && followUpPending?.status === "confirming"
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

        ${followUpEnabled && !isIesReport && followUpPending?.status === "loading"
      ? html`<${FollowUpCard} entry=${followUpPending} />`
      : null}

        ${followUpEnabled && !isIesReport && followUps.length
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
                        majorPlayers=${entry.result?.major_players || []}
                        emergingPlayers=${entry.result?.emerging_players || []}
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
  followUpEnabled,
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
      <div className="workspace-pane-body my-auto min-h-0 flex-1 flex flex-col justify-center overflow-hidden">
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
                  followUpEnabled=${followUpEnabled}
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
  const followUpEnabled = isFollowUpEnabled();
  const [isProcessing, setIsProcessing] = useState(false);
  const [topic, setTopic] = useState("");
  const [section, setSection] = useState("");
  const [snapshotSector, setSnapshotSector] = useState("");
  const [snapshotIndustry, setSnapshotIndustry] = useState("");
  const [snapshotCoverage, setSnapshotCoverage] = useState("");
  const [snapshotCatalog, setSnapshotCatalog] = useState({ sectors: [], industriesBySector: {} });
  const [snapshotCatalogLoading, setSnapshotCatalogLoading] = useState(false);
  const [snapshotCatalogError, setSnapshotCatalogError] = useState("");
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
  const pollResearchJob = createResearchJobPoller({
    apiUrl,
    buildErrorMessage,
    buildJobProgressMessage,
    reducedMotion,
    appendLiveJournalMessage,
  });
  const hasSelectedModule = Boolean(section);
  const isEarningsSnapshot = section === "industry_earnings_snapshot";

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
    fetch(withStaticAssetVersion("/ui/pencil-loader.css"), { cache: "force-cache" }).catch(() => { });
    fetch(withStaticAssetVersion("/ui/pencil-loader.html"), { cache: "force-cache" }).catch(() => { });
  }, []);

  useEffect(() => {
    if (!isEarningsSnapshot) {
      setSnapshotCatalogLoading(false);
      return;
    }

    if (cachedIesCatalog) {
      setSnapshotCatalog(cachedIesCatalog);
      setSnapshotCatalogError("");
      setSnapshotCatalogLoading(false);
      return;
    }

    let cancelled = false;

    async function loadSnapshotCatalog() {
      setSnapshotCatalogLoading(true);
      setSnapshotCatalogError("");

      try {
        const normalizedCatalog = await loadIesCatalog();

        if (!cancelled) {
          startTransition(() => {
            setSnapshotCatalog(normalizedCatalog);
            setSnapshotCatalogError("");
          });
        }
      } catch (error) {
        if (!cancelled) {
          const message =
            error instanceof Error
              ? error.message
              : "The IES catalog could not be loaded from the database.";
          setSnapshotCatalogError(message);
          setSnapshotCatalog({ sectors: [], industriesBySector: {} });
        }
      } finally {
        if (!cancelled) {
          setSnapshotCatalogLoading(false);
        }
      }
    }

    loadSnapshotCatalog();
    return () => {
      cancelled = true;
    };
  }, [isEarningsSnapshot]);

  useEffect(() => {
    setLocationValue("");
    setRegionQuery("");
    setCountryQuery("");
    setSecondaryFilterOpen(locationPreference !== "global");
  }, [locationPreference]);

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
  const snapshotSectorOptions = snapshotCatalog.sectors;
  const snapshotIndustryOptions =
    snapshotCatalog.industriesBySector[String(snapshotSector || "").trim()] || [];
  const snapshotTopicPreview = buildIndustryEarningsSnapshotTopic({
    sectorOptions: snapshotSectorOptions,
    industriesBySector: snapshotCatalog.industriesBySector,
    coverageOptions: INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS,
    sector: snapshotSector,
    industry: snapshotIndustry,
    coverage: snapshotCoverage,
    locationLabel: currentLocationMeta.label,
  });
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
        topic: isEarningsSnapshot ? snapshotTopicPreview : topic.trim(),
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

  function handleSnapshotSectorChange(value) {
    setSnapshotSector(value);
    setSnapshotIndustry("");
  }

  function toggleFollowUpComposer() {
    if (!followUpEnabled || isProcessing) {
      return;
    }
    setFollowUpOpen((current) => !current);
    setFollowUpPending(null);
  }

  async function requestFollowUpDecision(queryText) {
    if (!followUpEnabled) {
      return;
    }

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
    if (!followUpEnabled || !followUpPending?.payload || isProcessing) {
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
            feature_flags: buildFeatureFlags(resultSection),
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

      if (decision !== "SUFFICIENT") {
        const completedJobPayload = await pollResearchJob(responsePayload?.job_id, resultSection, (jobPayload) => {
          setFollowUpPending((current) =>
            current
              ? {
                ...current,
                status: "loading",
                loading_message: buildJobProgressMessage(jobPayload, resultSection),
                progress_percentage: Number(jobPayload?.progress_percentage || 0),
              }
              : current,
          );
        });
        responsePayload = completedJobPayload?.result || null;
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
    if (!followUpEnabled) {
      return;
    }

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

  function appendLiveJournalMessage(message) {
    const normalized = String(message || "").trim();
    if (!normalized) {
      return;
    }

    journalSeedRef.current += 1;
    setLiveJournal((previous) => {
      if (previous.length && previous[previous.length - 1]?.message === normalized) {
        return previous;
      }
      return [
        ...previous,
        {
          id: `journal-${Date.now()}-${journalSeedRef.current}`,
          message: normalized,
        },
      ].slice(-6);
    });
  }

  async function handleFollowUpSubmit(event) {
    event.preventDefault();
    if (!followUpEnabled || isProcessing) {
      return;
    }
    await requestFollowUpDecision(followUpQuery);
  }

  async function handleAnalyze(event) {
    event.preventDefault();
    if (isProcessing) {
      return;
    }

    if (!section) {
      setAnalysisError("Choose a module from the fixed top selector before launching analysis.");
      setAnalysisState("error");
      return;
    }

    const trimmedTopic = topic.trim();
    const snapshotTopic = buildIndustryEarningsSnapshotTopic({
      sectorOptions: snapshotSectorOptions,
      industriesBySector: snapshotCatalog.industriesBySector,
      coverageOptions: INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS,
      sector: snapshotSector,
      industry: snapshotIndustry,
      coverage: snapshotCoverage,
      locationLabel: locationValue || currentLocationMeta.label,
    });

    if (isEarningsSnapshot) {
      if (snapshotCatalogLoading) {
        setAnalysisError("Loading the industry earnings catalog from the database. Please wait a moment.");
        setAnalysisState("error");
        return;
      }
      if (snapshotCatalogError) {
        setAnalysisError(snapshotCatalogError);
        setAnalysisState("error");
        return;
      }
      if (!snapshotSector) {
        setAnalysisError("Choose a sector before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (!snapshotSectorOptions.some((option) => option.value === snapshotSector)) {
        setAnalysisError("Choose a sector from the loaded database options before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (!snapshotIndustry) {
        setAnalysisError("Choose an industry before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (!snapshotIndustryOptions.some((option) => option.value === snapshotIndustry)) {
        setAnalysisError("Choose an industry from the loaded database options before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (!snapshotCoverage) {
        setAnalysisError("Choose a coverage level before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (!INDUSTRY_EARNINGS_SNAPSHOT_COVERAGE_OPTIONS.some((option) => option.value === snapshotCoverage)) {
        setAnalysisError("Choose a valid coverage level before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
      if (locationPreference !== "global" && !locationValue) {
        setAnalysisError("Choose a region or country before launching the earnings snapshot.");
        setAnalysisState("error");
        return;
      }
    } else if (!trimmedTopic) {
      setAnalysisError("Enter a topic before running analysis.");
      setAnalysisState("error");
      return;
    }

    if (!isEarningsSnapshot && locationPreference !== "global" && !locationValue) {
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
      setProgressValue(8);
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
        topic: isEarningsSnapshot ? snapshotTopic : trimmedTopic,
        location: requestedLocation,
      });
    });

    await new Promise((resolve) => {
      window.requestAnimationFrame(() => resolve());
    });

    try {
      if (isEarningsSnapshot) {
        const snapshotScope = getIesReportScope(locationPreference, locationValue);
        const response = await fetch(apiUrl("/api/ies-report"), {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            industry: snapshotIndustry,
            filter_type: snapshotScope.filter_type,
            filter_value: snapshotScope.filter_value,
            top_n: getIesReportTopN(snapshotCoverage),
          }),
        });

        let responsePayload = null;
        try {
          responsePayload = await response.json();
        } catch {
          responsePayload = null;
        }

        if (!response.ok) {
          throw new Error(buildErrorMessage(responsePayload, "IES report failed. Please try again."));
        }

        const normalizedPayload = normalizeIesReportResponse(responsePayload);
        if (!normalizedPayload) {
          throw new Error("IES report returned an unexpected response shape.");
        }

        startTransition(() => {
          const responseMeta = {
            topic: normalizedPayload?.meta?.topic || snapshotTopic,
            location: normalizedPayload?.meta?.location || requestedLocation,
          };
          setAnalysisResult(normalizedPayload);
          setAnalysisDebug(null);
          setAnalysisMeta(responseMeta);
          setProgressValue((current) => Math.max(current, 100));
          setLiveJournal(buildCompletedJournal(normalizedPayload, null, responseMeta));
          setAnalysisState("completed");
        });
        return;
      }

      const response = await fetch(apiUrl("/api/research"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          topic: isEarningsSnapshot ? snapshotTopic : trimmedTopic,
          section,
          debug: true,
          feature_flags: buildFeatureFlags(section),
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

      const completedJobPayload = await pollResearchJob(payload?.job_id, section, (jobPayload) => {
        const nextProgress = Number(jobPayload?.progress_percentage || 0);
        setProgressValue((current) => Math.max(current, nextProgress));
      });
      const normalizedPayload = normalizeResearchResponse(completedJobPayload?.result, section);
      if (!normalizedPayload) {
        throw new Error("Analysis returned an unexpected response shape.");
      }

      startTransition(() => {
        const responseMeta = {
          topic: normalizedPayload?.meta?.topic || (isEarningsSnapshot ? snapshotTopic : trimmedTopic),
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
      <div
        className=${cx(
    "workspace-grid relative z-10 grid min-h-full gap-3 px-3 py-3 md:gap-4 md:px-4 md:py-4 xl:px-5 xl:py-5",
    hasSelectedModule
      ? "grid-rows-[auto_auto_auto_minmax(0,1fr)]"
      : "grid-rows-[auto_auto]",
  )}
      >
        <${WorkspaceHeader}
          currentLocation=${displayMeta.location}
        />

        <${ModuleSelectorBar}
          section=${section}
          onSectionChange=${setSection}
          disabled=${isProcessing}
        />

        ${hasSelectedModule
      ? html`
              <${CommandDeck}
                topic=${topic}
                section=${section}
                snapshotSector=${snapshotSector}
                snapshotIndustry=${snapshotIndustry}
                snapshotCoverage=${snapshotCoverage}
                snapshotSectorOptions=${snapshotSectorOptions}
                snapshotIndustryOptions=${snapshotIndustryOptions}
                snapshotCatalogLoading=${snapshotCatalogLoading}
                snapshotCatalogError=${snapshotCatalogError}
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
                onSnapshotSectorChange=${handleSnapshotSectorChange}
                onSnapshotIndustryChange=${setSnapshotIndustry}
                onSnapshotCoverageChange=${setSnapshotCoverage}
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
            "workspace-main grid min-h-0 gap-4 transition-opacity duration-200 xl:grid-cols-[minmax(0,0.56fr)_minmax(0,1.44fr)]",
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
                          followUpEnabled=${followUpEnabled}
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
            `
      : null}
      </div>
    </div>
  `;
}

const rootElement = document.getElementById("root");
window.__RESEARCH_PAGE_ID__ = RESEARCH_PAGE_ID;
mountApp(rootElement, createRoot, html, App);
