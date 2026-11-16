import React, { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  FastForward,
  Pause,
  Play,
  RotateCcw,
  StepForward,
} from "lucide-react";
import { DaySimulationStatus, LLMTelemetrySnapshot } from "../types";

interface Props {
  simStatus: DaySimulationStatus | null;
  telemetry: LLMTelemetrySnapshot | null;
  busyAction: string | null;
  onStep: () => Promise<void>;
  onRunFullDay: () => Promise<void>;
  onResetDay: () => Promise<void>;
}

export const DaySimulationTimeline: React.FC<Props> = ({
  simStatus,
  telemetry,
  busyAction,
  onStep,
  onRunFullDay,
  onResetDay,
}) => {
  const [showDrawer, setShowDrawer] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);

  useEffect(() => {
    if (!autoPlay || !simStatus || simStatus.is_day_completed || simStatus.status === "FAILED" || simStatus.status === "PENDING_REVIEW") {
      if ((simStatus?.is_day_completed || simStatus?.status === "FAILED" || simStatus?.status === "PENDING_REVIEW") && autoPlay) {
        setAutoPlay(false);
      }
      return;
    }
    if (busyAction !== null) return;

    const timer = setTimeout(() => {
      onStep();
    }, 2200);
    return () => clearTimeout(timer);
  }, [autoPlay, simStatus, busyAction, onStep]);

  if (!simStatus) return null;

  const latestLog =
    simStatus.completed_logs.length > 0
      ? simStatus.completed_logs[simStatus.completed_logs.length - 1]
      : null;

  return (
    <section aria-label="隔离业务演练" className="border-b border-[#2d2e30] bg-[#18191b] px-4 py-1.5 text-xs">
      <div className="text-[11px] text-[#fdd663] mb-1 break-all">隔离演练 · Run {simStatus.run_id ?? "未提供"} · {simStatus.scope?.isolated === true ? "已隔离" : "隔离状态未提供"} · {simStatus.status ?? "状态未提供"}（不代表实际经营业绩）</div>
      <div className="text-[11px] text-[#9aa0a6] mb-1">成功 {simStatus.completed_logs.filter(log => log.status === "SUCCESS").length} · 失败 {simStatus.completed_logs.filter(log => log.status === "FAILED").length} · 待复核 {simStatus.completed_logs.filter(log => log.status === "PENDING_REVIEW").length}</div>
      {/* Compact Single-Row Studio Simulation Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] text-[#e3e3e3] font-mono text-[11px]">
            <Clock className="w-3.5 h-3.5 text-[#a8c7fa]" />
            <span>{simStatus.current_time}</span>
            <span className="text-[#9aa0a6]">
              ({simStatus.current_index}/{simStatus.total_stages})
            </span>
          </div>

          <button
            disabled={simStatus.is_day_completed}
            onClick={() => setAutoPlay((prev) => !prev)}
            className={`px-3 py-1 rounded-full font-medium flex items-center gap-1.5 transition text-[11px] ${
              autoPlay
                ? "bg-[#fdd663] text-[#131314]"
                : "bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f]"
            } disabled:opacity-40`}
          >
            {autoPlay ? (
              <>
                <Pause className="w-3 h-3 fill-current" />
                <span>Pause Auto</span>
              </>
            ) : (
              <>
                <Play className="w-3 h-3 fill-current" />
                <span>Auto-Simulate</span>
              </>
            )}
          </button>

          <button
            disabled={busyAction !== null || simStatus.is_day_completed}
            onClick={onStep}
            className="px-2.5 py-1 rounded-full bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#e3e3e3] flex items-center gap-1 disabled:opacity-40 transition text-[11px]"
          >
            <StepForward className="w-3 h-3 text-[#a8c7fa]" />
            <span>Step ({simStatus.next_stage?.time ?? "Done"})</span>
          </button>

          <button
            disabled={busyAction !== null || simStatus.is_day_completed}
            onClick={onRunFullDay}
            className="px-2.5 py-1 rounded-full bg-[#282a2c] hover:bg-[#35373a] border border-[#3c4043] text-[#9aa0a6] hover:text-[#e3e3e3] flex items-center gap-1 disabled:opacity-40 transition text-[11px]"
            title="Fast-forward full day (08:30–21:00)"
          >
            <FastForward className="w-3 h-3 text-[#a8c7fa]" />
            <span className="hidden sm:inline">21:00</span>
          </button>

          <button
            disabled={busyAction !== null}
            onClick={() => {
              setAutoPlay(false);
              onResetDay();
            }}
            className="p-1 rounded hover:bg-[#282a2c] text-[#9aa0a6] hover:text-[#e3e3e3] transition"
            title="Reset simulation clock to 08:00"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>

          {latestLog && (
            <div className="hidden xl:flex items-center gap-2 pl-2 border-l border-[#2d2e30] text-[11px]">
              <span className="font-mono text-[#a8c7fa]">{latestLog.time}</span>
              <span className="text-[#9aa0a6] truncate max-w-md">
                {latestLog.outcome_summary}
              </span>
            </div>
          )}
        </div>

        {/* Right: Compact Metrics & Drawer Toggle */}
        <div className="flex items-center gap-3 font-mono text-[11px] text-[#9aa0a6]">
          <span>
            GMV <b className="text-[#e3e3e3]">¥{simStatus.metrics.gmv_cny.toLocaleString()}</b>
          </span>
          <span>
            Orders <b className="text-[#e3e3e3]">{simStatus.metrics.orders_processed}</b>
          </span>
          <span>
            Skills <b className="text-[#81c995]">{simStatus.metrics.skills_minted}</b>
          </span>
          <span>
            Blocks{" "}
            <b className="text-[#f28b82]">
              {simStatus.metrics.redlines_blocked + simStatus.metrics.local_rollbacks}
            </b>
          </span>
          {telemetry && (
            <span className="hidden md:inline pl-2 border-l border-[#2d2e30]">
              L1/L2/L3:{" "}
              <b className="text-[#e3e3e3]">
                {telemetry.l1_sanitize_calls}/{telemetry.l2_fast_calls}/
                {telemetry.l3_reasoner_calls}
              </b>
            </span>
          )}
          <button
            onClick={() => setShowDrawer(!showDrawer)}
            className="px-2 py-0.5 rounded hover:bg-[#282a2c] text-[#a8c7fa] flex items-center gap-1 font-sans"
          >
            <span>Schedule</span>
            {showDrawer ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Collapsible 12-Tick Schedule & Execution Log Drawer */}
      {showDrawer && (
        <div className="mt-2 pt-2 border-t border-[#2d2e30] space-y-2">
          <div className="grid grid-cols-4 sm:grid-cols-6 lg:grid-cols-12 gap-1">
            {simStatus.schedule.map((item) => {
              const isDone = item.status === "DONE";
              const isNext = item.status === "NEXT";
              return (
                <div
                  key={item.phase}
                  title={`${item.time} · ${item.dept} · ${item.title}`}
                  className={`px-2 py-1 rounded border text-[10px] flex items-center justify-between ${
                    isDone
                      ? "bg-[#131314] border-[#3c4043] text-[#e3e3e3]"
                      : isNext
                      ? "bg-[#a8c7fa]/10 border-[#a8c7fa] text-[#a8c7fa]"
                      : "bg-[#131314]/50 border-[#2d2e30] text-[#5f6368]"
                  }`}
                >
                  <span className="font-mono">{item.time}</span>
                  <span className="truncate ml-1">{item.dept.split(" ")[0]}</span>
                  {isDone && <Check className="w-3 h-3 text-[#81c995] shrink-0" />}
                </div>
              );
            })}
          </div>

          {simStatus.completed_logs.length > 0 && (
            <div className="max-h-36 overflow-y-auto space-y-1 font-mono text-[11px]">
              {simStatus.completed_logs.map((log) => (
                <div
                  key={log.stage_index}
                  className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] flex items-center justify-between gap-4"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[#a8c7fa] shrink-0">{log.time}</span>
                    <span className="text-[#9aa0a6] shrink-0">[{log.dept}]</span>
                    <span className="text-[#e3e3e3] font-sans truncate">
                      {log.outcome_summary}
                    </span>
                  </div>
                  <span className={log.status === "SUCCESS" ? "text-[#81c995] shrink-0" : "text-[#fdd663] shrink-0"}>{log.status ?? "未提供状态"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
};
