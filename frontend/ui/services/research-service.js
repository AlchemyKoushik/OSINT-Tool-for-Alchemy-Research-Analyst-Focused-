export async function fetchResearchJobStatus(apiUrl, jobId) {
  return fetch(apiUrl(`/api/research/jobs/${encodeURIComponent(String(jobId || "").trim())}`), {
    method: "GET",
    cache: "no-store",
  });
}
