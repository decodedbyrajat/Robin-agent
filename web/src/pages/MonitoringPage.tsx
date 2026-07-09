import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  Clock,
  Cpu,
  Database,
  HardDrive,
  RefreshCw,
  Server,
  Thermometer,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AnalyticsResponse, StatusResponse, SystemHealthResponse } from "@/lib/api";
import { Button, Spinner } from "@nous-research/ui";
import { cn } from "@/lib/utils";
import { usePageHeader } from "@/contexts/usePageHeader";
import { useWakeLock } from "@/hooks/useWakeLock";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const INPUT_COST_PER_M = 0.242;
const OUTPUT_COST_PER_M = 3.94;

function calcCost(inputTokens: number, outputTokens: number): number {
  return (inputTokens * INPUT_COST_PER_M + outputTokens * OUTPUT_COST_PER_M) / 1_000_000;
}

function fmtCost(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmt(n: number, decimals = 0): string {
  return n.toFixed(decimals);
}

function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function thermalLabel(level: number | null | undefined): {
  label: string;
  color: string;
} {
  if (level == null) return { label: "unknown", color: "text-midground/40" };
  if (level === 0) return { label: "nominal", color: "text-success" };
  if (level === 1) return { label: "moderate", color: "text-warning" };
  return { label: "high", color: "text-destructive" };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface GaugeBarProps {
  percent: number;
  label: string;
  sublabel?: string;
  icon: typeof Cpu;
  warn?: number;
  crit?: number;
}

function GaugeBar({
  percent,
  label,
  sublabel,
  icon: Icon,
  warn = 70,
  crit = 90,
}: GaugeBarProps) {
  const color =
    percent >= crit
      ? "bg-destructive"
      : percent >= warn
        ? "bg-warning"
        : "bg-midground/80";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <Icon className="h-3 w-3 shrink-0 opacity-60" />
          <span className="text-[0.7rem] tracking-[0.1em] uppercase opacity-70 truncate">
            {label}
          </span>
        </div>
        <span
          className={cn(
            "text-[0.75rem] font-mono tabular-nums shrink-0",
            percent >= crit
              ? "text-destructive"
              : percent >= warn
                ? "text-warning"
                : "text-midground",
          )}
        >
          {fmt(percent)}%
        </span>
      </div>

      <div className="h-1.5 w-full bg-midground/10 overflow-hidden">
        <div
          className={cn("h-full transition-all duration-700", color)}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>

      {sublabel && (
        <span className="text-[0.65rem] opacity-40 tabular-nums">
          {sublabel}
        </span>
      )}
    </div>
  );
}

interface StatusPillProps {
  ok: boolean;
  label: string;
  detail?: string;
}

function StatusPill({ ok, label, detail }: StatusPillProps) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-midground/10 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        {ok ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" />
        ) : (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" />
        )}
        <span className="text-[0.75rem] tracking-[0.08em] truncate">{label}</span>
      </div>
      {detail && (
        <span className="text-[0.65rem] opacity-50 shrink-0 tabular-nums">
          {detail}
        </span>
      )}
    </div>
  );
}

interface SectionProps {
  title: string;
  icon: typeof Cpu;
  children: React.ReactNode;
  className?: string;
}

function Section({ title, icon: Icon, children, className }: SectionProps) {
  return (
    <div
      className={cn(
        "border border-midground/15 p-4 flex flex-col gap-4",
        className,
      )}
    >
      <div className="flex items-center gap-2 pb-1 border-b border-midground/10">
        <Icon className="h-3.5 w-3.5 opacity-50" />
        <span className="text-[0.65rem] tracking-[0.18em] uppercase opacity-50">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}

// Pulsing live indicator
function LiveDot() {
  return (
    <span className="relative flex h-2 w-2 shrink-0">
      <span className="animate-ping absolute inline-flex h-full w-full bg-success opacity-60" />
      <span className="relative inline-flex h-2 w-2 bg-success" />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const REFRESH_INTERVAL_MS = 15_000;

export default function MonitoringPage() {
  useWakeLock();
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const { setEnd } = usePageHeader();

  const load = useCallback(async () => {
    try {
      const [h, s, a] = await Promise.all([
        api.getSystemHealth(),
        api.getStatus(),
        api.getAnalytics(30),
      ]);
      setHealth(h);
      setStatus(s);
      setAnalytics(a);
      setLastRefreshed(new Date());
    } catch {
      // keep stale data
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    timerRef.current = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [load]);

  useLayoutEffect(() => {
    setEnd(
      <div className="flex items-center gap-3">
        {lastRefreshed && (
          <span className="text-[0.65rem] opacity-40 tabular-nums hidden sm:block">
            {lastRefreshed.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </span>
        )}
        <Button
          type="button"
          size="sm"
          outlined
          onClick={load}
          disabled={loading}
          prefix={loading ? <Spinner /> : <RefreshCw />}
        >
          Refresh
        </Button>
      </div>,
    );
    return () => setEnd(null);
  }, [load, loading, lastRefreshed, setEnd]);

  // ── Derived values ────────────────────────────────────────────────────────

  const gatewayOk = status?.gateway_running ?? false;
  const platforms = Object.entries(status?.gateway_platforms ?? {});
  const thermal = thermalLabel(health?.thermal_status);

  const uptimeStr = health?.uptime_seconds
    ? fmtUptime(health.uptime_seconds)
    : "—";

  const today = new Date().toISOString().slice(0, 10);
  const dailyEntries = analytics?.daily ?? [];
  const todayEntry = dailyEntries.find((d) => d.day === today);
  const todayCost = todayEntry ? calcCost(todayEntry.input_tokens, todayEntry.output_tokens) : 0;
  const cost7d = dailyEntries.slice(-7).reduce((s, d) => s + calcCost(d.input_tokens, d.output_tokens), 0);
  const cost30d = dailyEntries.reduce((s, d) => s + calcCost(d.input_tokens, d.output_tokens), 0);
  const activeDays = dailyEntries.filter((d) => d.input_tokens > 0 || d.output_tokens > 0).length;
  const projMonthly = activeDays > 0 ? (cost30d / activeDays) * 30 : 0;

  return (
    <div className="flex flex-col gap-1 pb-2">
      {/* ── Top status bar ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3 py-2 mb-2 border-b border-midground/10">
        {gatewayOk ? (
          <LiveDot />
        ) : (
          <Circle className="h-2 w-2 text-destructive fill-current" />
        )}
        <span className="text-[0.7rem] tracking-[0.15em] uppercase opacity-60">
          {gatewayOk ? "gateway online" : "gateway offline"}
        </span>
        {status?.version && (
          <span className="text-[0.65rem] opacity-30 ml-auto font-mono">
            v{status.version}
          </span>
        )}
      </div>

      {loading && !health && (
        <div className="flex items-center justify-center py-24">
          <Spinner className="text-2xl" />
        </div>
      )}

      {/* ── Main grid ──────────────────────────────────────────────── */}
      {(health || status) && (
        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {/* Mac system resources */}
          <Section title="System Resources" icon={Cpu}>
            {health?.cpu_percent != null && (
              <GaugeBar
                percent={health.cpu_percent}
                label="CPU"
                icon={Cpu}
                warn={60}
                crit={85}
              />
            )}
            {health?.memory_percent != null && (
              <GaugeBar
                percent={health.memory_percent}
                label="Memory"
                sublabel={
                  health.memory_used_gb != null && health.memory_total_gb != null
                    ? `${fmt(health.memory_used_gb, 1)} / ${fmt(health.memory_total_gb, 1)} GB`
                    : undefined
                }
                icon={Server}
                warn={75}
                crit={92}
              />
            )}
            {health?.disk_percent != null && (
              <GaugeBar
                percent={health.disk_percent}
                label="Disk"
                sublabel={
                  health.disk_used_gb != null && health.disk_total_gb != null
                    ? `${fmt(health.disk_used_gb, 0)} / ${fmt(health.disk_total_gb, 0)} GB`
                    : undefined
                }
                icon={HardDrive}
                warn={80}
                crit={95}
              />
            )}

            <div className="flex items-center justify-between pt-1">
              <div className="flex items-center gap-1.5">
                <Clock className="h-3 w-3 opacity-40" />
                <span className="text-[0.65rem] opacity-40 tracking-[0.08em] uppercase">
                  uptime
                </span>
              </div>
              <span className="text-[0.75rem] font-mono tabular-nums opacity-70">
                {uptimeStr}
              </span>
            </div>

            {health?.thermal_status != null && (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <Thermometer className="h-3 w-3 opacity-40" />
                  <span className="text-[0.65rem] opacity-40 tracking-[0.08em] uppercase">
                    thermal
                  </span>
                </div>
                <span
                  className={cn(
                    "text-[0.75rem] tracking-[0.08em] uppercase",
                    thermal.color,
                  )}
                >
                  {thermal.label}
                </span>
              </div>
            )}
          </Section>

          {/* Gateway & platforms */}
          <Section title="Gateway" icon={Server}>
            <StatusPill
              ok={gatewayOk}
              label="Robin gateway"
              detail={
                status?.gateway_pid ? `pid ${status.gateway_pid}` : undefined
              }
            />
            <StatusPill
              ok={status?.active_sessions != null}
              label="Active sessions"
              detail={
                status?.active_sessions != null
                  ? `${status.active_sessions}`
                  : undefined
              }
            />

            {platforms.length > 0 && (
              <div className="flex flex-col gap-0.5 mt-1">
                <span className="text-[0.6rem] tracking-[0.15em] uppercase opacity-30 mb-1">
                  platforms
                </span>
                {platforms.map(([name, p]) => (
                  <StatusPill
                    key={name}
                    ok={p.state === "running" || p.state === "connected"}
                    label={name}
                    detail={p.state}
                  />
                ))}
              </div>
            )}
          </Section>

          {/* Ollama / models */}
          <Section title="Local Models" icon={Zap}>
            <StatusPill
              ok={health?.ollama_running ?? false}
              label="Ollama daemon"
              detail={
                health?.ollama_running
                  ? `${(health.ollama_models ?? []).length} model${(health.ollama_models ?? []).length !== 1 ? "s" : ""} loaded`
                  : "offline"
              }
            />

            {(health?.ollama_models ?? []).map((m) => (
              <div
                key={m}
                className="flex items-center gap-2 py-1 border-b border-midground/10 last:border-0"
              >
                <Database className="h-3 w-3 shrink-0 opacity-30" />
                <span className="text-[0.7rem] font-mono opacity-70 truncate">
                  {m}
                </span>
              </div>
            ))}

            {health?.ollama_running === false && (
              <p className="text-[0.7rem] opacity-40 italic">
                Start with: <code className="font-mono not-italic">ollama serve</code>
              </p>
            )}
          </Section>

          {/* Network / connectivity */}
          <Section title="Connectivity" icon={Wifi} className="lg:col-span-2 xl:col-span-1">
            <StatusPill
              ok={gatewayOk}
              label="API server"
              detail={gatewayOk ? "reachable" : "down"}
            />
            <StatusPill
              ok={health?.ollama_running ?? false}
              label="Ollama endpoint"
              detail="localhost:11434"
            />
            {platforms.filter(([, p]) => p.state !== "running" && p.state !== "connected").map(([name, p]) => (
              <div
                key={name}
                className="flex items-center gap-2 text-[0.7rem] text-warning py-1"
              >
                <WifiOff className="h-3 w-3 shrink-0" />
                <span className="truncate">{name}: {p.error_message ?? p.state}</span>
              </div>
            ))}
            {platforms.every(([, p]) => p.state === "running" || p.state === "connected") &&
              platforms.length > 0 && (
                <p className="text-[0.65rem] opacity-40 italic">
                  All platforms connected
                </p>
              )}
          </Section>

          {/* Quick stats */}
          <Section title="Quick Stats" icon={Activity} className="lg:col-span-2">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {[
                {
                  label: "Active sessions",
                  value: status?.active_sessions ?? "—",
                },
                {
                  label: "Platforms",
                  value: platforms.length > 0 ? platforms.length : "—",
                },
                {
                  label: "Local models",
                  value: health?.ollama_models?.length ?? "—",
                },
                {
                  label: "Host uptime",
                  value: uptimeStr,
                },
              ].map(({ label, value }) => (
                <div key={label} className="flex flex-col gap-1">
                  <span className="text-[0.6rem] tracking-[0.15em] uppercase opacity-40">
                    {label}
                  </span>
                  <span className="text-[1.1rem] font-mono tabular-nums leading-tight">
                    {String(value)}
                  </span>
                </div>
              ))}
            </div>
          </Section>

          {/* Cost estimate */}
          {analytics && (
            <Section title="Cost Estimate" icon={Zap} className="lg:col-span-2 xl:col-span-1">
              <div className="grid grid-cols-2 gap-4">
                {[
                  { label: "Today", value: fmtCost(todayCost) },
                  { label: "Last 7 days", value: fmtCost(cost7d) },
                  { label: "Last 30 days", value: fmtCost(cost30d) },
                  { label: "Proj. monthly", value: fmtCost(projMonthly) },
                ].map(({ label, value }) => (
                  <div key={label} className="flex flex-col gap-1">
                    <span className="text-[0.6rem] tracking-[0.15em] uppercase opacity-40">
                      {label}
                    </span>
                    <span className="text-[1.1rem] font-mono tabular-nums leading-tight">
                      {value}
                    </span>
                  </div>
                ))}
              </div>
              <div className="pt-1 border-t border-midground/10">
                <span className="text-[0.6rem] opacity-25 tabular-nums">
                  ${INPUT_COST_PER_M}/1M in · ${OUTPUT_COST_PER_M}/1M out
                </span>
              </div>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}
