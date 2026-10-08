/**
 * Manages live Server-Sent Events (SSE) from /api/events
 * and coordinates auto-refresh when Supabase changes.
 */

export function setupLiveEvents(onUpdate, onStatusChange) {
  let es = null;
  let retryTimer = null;

  function connect() {
    try {
      es = new EventSource("/api/events");

      es.addEventListener("ready", ev => {
        let d = {};
        try { d = JSON.parse(ev.data); } catch {}
        if (d.serverless) {
          onStatusChange("snapshot", "snapshot");
          es.close();
          return;
        }
        onStatusChange("live", "live");
      });

      es.addEventListener("change", ev => {
        let tables = [];
        try { tables = JSON.parse(ev.data).tables || []; } catch {}
        const txt = tables.length
          ? `updated · ${tables.length} table${tables.length === 1 ? "" : "s"}`
          : "updated";
        onStatusChange("live", txt);
        onUpdate();
        setTimeout(() => onStatusChange("live", "live"), 2500);
      });

      es.onerror = () => {
        if (window.location.hostname.includes("vercel.app")) {
          onStatusChange("live", "snapshot");
          es?.close();
        } else {
          onStatusChange("down", "reconnecting");
          es?.close();
          clearTimeout(retryTimer);
          retryTimer = setTimeout(connect, 5000);
        }
      };

      es.onopen = () => {
        onStatusChange("live", "live");
      };
    } catch (e) {
      console.warn("SSE not available:", e);
      onStatusChange("down", "offline");
    }
  }

  connect();

  // Auto-sync whenever user focuses the browser tab or returns from Supabase Studio
  const handleFocus = () => onUpdate();
  const handleVisibility = () => {
    if (document.visibilityState === "visible") onUpdate();
  };

  window.addEventListener("focus", handleFocus);
  document.addEventListener("visibilitychange", handleVisibility);

  // Periodic heartbeat sync (every 25s) to guarantee updates
  const interval = setInterval(() => {
    if (document.visibilityState === "visible") onUpdate();
  }, 25000);

  return () => {
    es?.close();
    clearTimeout(retryTimer);
    clearInterval(interval);
    window.removeEventListener("focus", handleFocus);
    document.removeEventListener("visibilitychange", handleVisibility);
  };
}
