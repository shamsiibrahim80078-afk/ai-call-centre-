import LiveRequestsPage from "./LiveRequestsPage";

const INVESTIGATION_PRESET_KEY = "veridiq_request_preset";
const INVESTIGATION_PRESET =
  "Investigate this company for diligence risks and evidence.";

/** Investigation Center — focused entry into orchestrated investigation requests. */
export default function InvestigationPage() {
  // Must set before LiveRequestsPage mounts so useState init picks it up.
  if (typeof sessionStorage !== "undefined") {
    sessionStorage.setItem(INVESTIGATION_PRESET_KEY, INVESTIGATION_PRESET);
  }
  return (
    <LiveRequestsPage title="Investigation Center" presetKey={INVESTIGATION_PRESET_KEY} />
  );
}
