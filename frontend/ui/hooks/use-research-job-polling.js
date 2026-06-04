import { fetchResearchJobStatus } from "../services/research-service.js";

export function createResearchJobPoller({
  apiUrl,
  buildErrorMessage,
  buildJobProgressMessage,
  reducedMotion,
  appendLiveJournalMessage,
}) {
  return async function pollResearchJob(jobId, fallbackSection, onProgress) {
    const normalizedJobId = String(jobId || "").trim();
    if (!normalizedJobId) {
      throw new Error("Research job ID missing from backend response.");
    }

    while (true) {
      const response = await fetchResearchJobStatus(apiUrl, normalizedJobId);
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      if (!response.ok) {
        throw new Error(buildErrorMessage(payload, "Research job status could not be loaded."));
      }

      if (typeof onProgress === "function") {
        onProgress(payload);
      }

      const status = String(payload?.status || "").trim().toLowerCase();
      if (status === "completed") {
        return payload;
      }
      if (status === "failed") {
        throw new Error(buildErrorMessage(payload, "Research job failed."));
      }

      appendLiveJournalMessage(buildJobProgressMessage(payload, fallbackSection));
      await new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 1400 : 900));
    }
  };
}
