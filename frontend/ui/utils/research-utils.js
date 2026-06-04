export function buildJobProgressMessage(jobPayload, fallbackSection = "trends") {
  const stage = String(jobPayload?.stage || "").trim();
  const activity = String(jobPayload?.current_activity || "").trim();
  if (activity) {
    return activity;
  }
  if (stage) {
    return `${stage}...`;
  }
  if (fallbackSection === "competitive_landscape") {
    return "Preparing the competitive landscape briefing...";
  }
  if (fallbackSection === "drivers") {
    return "Preparing the market drivers briefing...";
  }
  return "Preparing the industry trends briefing...";
}
