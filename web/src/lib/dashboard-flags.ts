declare global {
  interface Window {
    /** Set true by the server only for `robin dashboard --tui` (or ROBIN_DASHBOARD_TUI=1). */
    __ROBIN_DASHBOARD_EMBEDDED_CHAT__?: boolean;
    /** @deprecated Older injected name; treated as on when true. */
    __ROBIN_DASHBOARD_TUI__?: boolean;
  }
}

/** True only when the dashboard was started with embedded TUI Chat (`robin dashboard --tui`). */
export function isDashboardEmbeddedChatEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (window.__ROBIN_DASHBOARD_EMBEDDED_CHAT__ === true) return true;
  return window.__ROBIN_DASHBOARD_TUI__ === true;
}
