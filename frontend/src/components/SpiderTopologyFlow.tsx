import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Edge,
  MarkerType,
  Node,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ChevronDown,
  Eye,
  EyeOff,
  Flame,
  Flashlight,
  Loader2,
  Maximize2,
  MessageSquare,
  RotateCcw,
  Sparkles,
  Square,
  X,
  ZoomIn,
} from "lucide-react";
import {
  fetchCaveExplorationMap,
  plantTorchAndWeave,
  resetToEmptyShell,
  scoutOrganizationStructure,
  toggleSpiderNodeLifecycle,
} from "../api";
import {
  CaveExplorationMapResponse,
  CaveNodeDetail,
  CustodyBallItem,
  SpiderNode,
  WeavePointItem,
} from "../types";

interface Props {
  nodesData: SpiderNode[];
  canControlDrills: boolean;
  busyAction: string | null;
  onDrill: (
    mode: "BURST_PAD" | "HALLUCINATION_FAULT" | "DEHYDRATE_IDLE" | "BORROW_BALL"
  ) => void;
  onRefreshAll?: () => Promise<void>;
  onQuickUse?: (
    promptText: string,
    ballType: CustodyBallItem["ball_type"]
  ) => void;
  onToast?: (text: string, kind?: "ok" | "err") => void;
}

const NODE_META_BY_TYPE: Record<
  SpiderNode["node_type"],
  { accent: string; tag: string }
> = {
  BOARD_ROOT: { accent: "#fbbf24", tag: "初始火种" },
  ASPECT_NODE: { accent: "#34d399", tag: "业务部门" },
  RELAY_NODE: { accent: "#fbbf24", tag: "审批复核" },
  WORKER_SLOT: { accent: "#60a5fa", tag: "执行岗位" },
  BLACKBOX_HUMAN: { accent: "#f87171", tag: "专岗黑盒" },
};

const WEAVE_TYPE_STYLE: Record<
  WeavePointItem["ball_type"],
  { label: string; color: string; bg: string; border: string }
> = {
  DATA: {
    label: "资料",
    color: "#93c5fd",
    bg: "#172554",
    border: "#3b82f6",
  },
  SKILL: {
    label: "工具",
    color: "#6ee7b7",
    bg: "#064e3b",
    border: "#10b981",
  },
  AUTHORITY: {
    label: "审批",
    color: "#fcd34d",
    bg: "#451a03",
    border: "#f59e0b",
  },
  REDLINE: {
    label: "底线",
    color: "#fca5a5",
    bg: "#450a0a",
    border: "#ef4444",
  },
};

function cleanDisplayLabel(rawLabel: string): string {
  return rawLabel
    .replace(/【|】/g, "")
    .replace(/分面中枢/g, "")
    .replace(/\((?:SLOT|node)[^)]*\)/gi, "")
    .trim();
}

const SpiderTopologyFlowInner: React.FC<Props> = ({
  nodesData,
  canControlDrills,
  busyAction,
  onDrill,
  onRefreshAll,
  onQuickUse,
  onToast,
}) => {
  const { fitView, setCenter, zoomTo } = useReactFlow();

  const [caveMap, setCaveMap] = useState<CaveExplorationMapResponse | null>(
    null
  );
  const [loadingMap, setLoadingMap] = useState<boolean>(true);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [showAllWeavePoints, setShowAllWeavePoints] = useState<boolean>(false);

  // Scout modal state
  const [scoutModalOpen, setScoutModalOpen] = useState<boolean>(false);
  const [scoutName, setScoutName] = useState<string>("杭州丝语女装柔性快反工厂");
  const [scoutMaterial, setScoutMaterial] = useState<string>("");

  // Plant torch SOP input
  const [sopDraft, setSopDraft] = useState<string>("");

  // Drills dropdown
  const [drillsOpen, setDrillsOpen] = useState<boolean>(false);

  // Auto patrol demo state
  const [demoRunning, setDemoRunning] = useState<boolean>(false);
  const [demoHint, setDemoHint] = useState<string>("");
  const demoAbortRef = useRef<boolean>(false);

  const loadCaveMap = useCallback(async () => {
    try {
      const data = await fetchCaveExplorationMap();
      setCaveMap(data);
      setScoutMaterial((prev) =>
        prev ? prev : data.starter_dossiers?.[0]?.raw_org_material ?? ""
      );
    } catch (err) {
      onToast?.(
        err instanceof Error ? err.message : "加载探索地图失败",
        "err"
      );
    } finally {
      setLoadingMap(false);
    }
  }, [onToast]);

  useEffect(() => {
    loadCaveMap();
  }, [loadCaveMap, nodesData]);

  // Refit view cleanly when node count changes drastically (e.g., reset to empty shell or scout)
  const prevNodeCountRef = useRef<number>(0);
  useEffect(() => {
    const count = caveMap?.nodes.length ?? 0;
    if (count > 0 && count !== prevNodeCountRef.current) {
      prevNodeCountRef.current = count;
      const timer = setTimeout(() => {
        fitView({ padding: count === 1 ? 0.55 : 0.22, duration: 420 });
      }, 60);
      return () => clearTimeout(timer);
    }
  }, [caveMap?.nodes.length, fitView]);

  const effectiveNodes: CaveNodeDetail[] = useMemo(() => {
    if (caveMap?.nodes) return caveMap.nodes;
    return nodesData.map((n) => ({
      ...n,
      exploration_state: n.exploration_state ?? "LIT",
      torch_planted: n.torch_planted ?? true,
      discovered_from: n.discovered_from ?? "",
      weave_points: [],
    }));
  }, [caveMap?.nodes, nodesData]);

  const selectedCaveNode = useMemo(
    () => effectiveNodes.find((n) => n.node_id === selectedId) ?? null,
    [effectiveNodes, selectedId]
  );

  const selectedWeavePoint = useMemo(() => {
    if (!selectedId || !selectedId.startsWith("weave-")) return null;
    const pid = selectedId.slice("weave-".length);
    for (const n of effectiveNodes) {
      const found = n.weave_points.find((w) => w.point_id === pid);
      if (found) return { point: found, hostNode: n };
    }
    return null;
  }, [effectiveNodes, selectedId]);

  const handleResetEmptyShell = useCallback(async () => {
    setActionBusy("reset");
    setSelectedId(null);
    setShowAllWeavePoints(false);
    try {
      const next = await resetToEmptyShell({ enterprise_name: "待探索企业" });
      setCaveMap(next);
      onToast?.("已重置为空瓶壳子：一片黑暗中仅保留中央 1 个初始火种");
      await onRefreshAll?.();
    } catch (err) {
      onToast?.(err instanceof Error ? err.message : "重置失败", "err");
    } finally {
      setActionBusy(null);
    }
  }, [onRefreshAll, onToast]);

  const handleScoutSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      if (!scoutMaterial.trim()) {
        onToast?.("请先输入企业简介或选择一份档案小样", "err");
        return;
      }
      setActionBusy("scout");
      setSelectedId(null);
      try {
        const next = await scoutOrganizationStructure({
          enterprise_name: scoutName.trim() || "待探索企业",
          raw_org_material: scoutMaterial.trim(),
        });
        setCaveMap(next);
        setScoutModalOpen(false);
        onToast?.(
          `火把探路完成：摸清 ${next.stats.scouted_nodes} 个灰色轮廓节点，点击任意节点即可插火把织网`
        );
        await onRefreshAll?.();
      } catch (err) {
        onToast?.(err instanceof Error ? err.message : "探路失败", "err");
      } finally {
        setActionBusy(null);
      }
    },
    [onRefreshAll, onToast, scoutMaterial, scoutName]
  );

  const handlePlantTorch = useCallback(
    async (nodeId: string, customSop?: string) => {
      setActionBusy(`torch:${nodeId}`);
      try {
        const next = await plantTorchAndWeave({
          target_node_id: nodeId,
          raw_sop_text: customSop ?? sopDraft,
        });
        setCaveMap(next);
        setSopDraft("");
        setSelectedId(nodeId);
        onToast?.("常驻火把已点亮，业务内容与协作丝线已自动织入");
        await onRefreshAll?.();
      } catch (err) {
        onToast?.(err instanceof Error ? err.message : "插火把失败", "err");
      } finally {
        setActionBusy(null);
      }
    },
    [onRefreshAll, onToast, sopDraft]
  );

  const handleRunAutoPatrol = useCallback(async () => {
    if (demoRunning) {
      demoAbortRef.current = true;
      setDemoRunning(false);
      setDemoHint("");
      return;
    }
    demoAbortRef.current = false;
    setDemoRunning(true);
    setSelectedId(null);
    setShowAllWeavePoints(false);

    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

    try {
      setDemoHint("① 回到空瓶壳子：一片黑暗，只留 1 个初始火种...");
      const emptyState = await resetToEmptyShell({
        enterprise_name: scoutName.trim() || "杭州丝语女装柔性快反工厂",
      });
      setCaveMap(emptyState);
      await sleep(950);
      if (demoAbortRef.current) return;

      const dossier =
        emptyState.starter_dossiers?.[0] ??
        ({
          enterprise_name: scoutName.trim() || "杭州丝语女装柔性快反工厂",
          raw_org_material:
            scoutMaterial.trim() ||
            "杭州丝语女装柔性快反工厂，设市场跟单部、面辅料采购部、版房品控部与财务结算部。",
        } as const);

      setDemoHint("② 拿火把探路：散开局域黑雾，摸清灰色部门与岗位轮廓...");
      const scoutedState = await scoutOrganizationStructure({
        enterprise_name: dossier.enterprise_name,
        raw_org_material: dossier.raw_org_material,
      });
      setCaveMap(scoutedState);
      await sleep(1100);
      if (demoAbortRef.current) return;

      const targetPositions = scoutedState.nodes.filter(
        (n) =>
          n.exploration_state === "SCOUTED" && n.node_type !== "ASPECT_NODE"
      );
      let latestState = scoutedState;
      for (let i = 0; i < targetPositions.length; i++) {
        if (demoAbortRef.current) return;
        const pos = targetPositions[i];
        const labelShort = cleanDisplayLabel(pos.label);
        setDemoHint(
          `③ 插下第 ${i + 1}/${targetPositions.length} 支火把：正在照亮「${labelShort}」并织网...`
        );
        latestState = await plantTorchAndWeave({
          target_node_id: pos.node_id,
          raw_sop_text: "",
        });
        setCaveMap(latestState);
        if (i === targetPositions.length - 1) {
          setShowAllWeavePoints(true);
        }
        await sleep(800);
      }

      if (!demoAbortRef.current) {
        setDemoHint("④ 全网火把已点亮，双击或放大画布可细看每个织网点！");
        onToast?.("矿洞巡探与自主织网演示完成");
        await onRefreshAll?.();
        setTimeout(() => {
          zoomTo(1.18, { duration: 550 });
        }, 120);
      }
    } catch (err) {
      onToast?.(err instanceof Error ? err.message : "自动巡洞出错", "err");
    } finally {
      setDemoRunning(false);
      setTimeout(() => setDemoHint(""), 4500);
    }
  }, [demoRunning, onRefreshAll, onToast, scoutMaterial, scoutName, zoomTo]);

  // Compute 2D coordinates + semantic zoom weave point satellites
  const { flowNodes, flowEdges, nodePositions } = useMemo(() => {
    const childrenMap = new Map<string | null, CaveNodeDetail[]>();
    for (const n of effectiveNodes) {
      const pid = n.parent_id ?? null;
      const arr = childrenMap.get(pid) ?? [];
      arr.push(n);
      childrenMap.set(pid, arr);
    }

    const levels: CaveNodeDetail[][] = [];
    const visited = new Set<string>();
    const roots = childrenMap.get(null) ?? [];
    if (roots.length > 0) {
      levels.push(roots);
      roots.forEach((r) => visited.add(r.node_id));
    }

    while (levels.length > 0) {
      const prev = levels[levels.length - 1];
      const next: CaveNodeDetail[] = [];
      for (const p of prev) {
        for (const k of childrenMap.get(p.node_id) ?? []) {
          if (!visited.has(k.node_id)) {
            visited.add(k.node_id);
            next.push(k);
          }
        }
      }
      if (next.length === 0) break;
      levels.push(next);
    }

    const unvisited = effectiveNodes.filter((n) => !visited.has(n.node_id));
    if (unvisited.length > 0) levels.push(unvisited);

    const posMap = new Map<string, { x: number; y: number }>();
    const positionedNodes: Node[] = [];
    const edges: Edge[] = [];

    const xSpacing = showAllWeavePoints || zoomLevel >= 1.15 ? 310 : 250;
    const ySpacing = showAllWeavePoints || zoomLevel >= 1.15 ? 195 : 148;

    levels.forEach((levelNodes, depth) => {
      const totalWidth = (levelNodes.length - 1) * xSpacing;
      const startX = -totalWidth / 2 + 420;
      const y = depth * ySpacing + 40;

      levelNodes.forEach((sn, idx) => {
        const nx = startX + idx * xSpacing;
        const ny = y;
        posMap.set(sn.node_id, { x: nx, y: ny });

        const meta = NODE_META_BY_TYPE[sn.node_type];
        const isScouted = sn.exploration_state === "SCOUTED";
        const isLit = !isScouted;
        const isSelected = selectedId === sn.node_id;
        const isAlert = sn.status === "ALERT" || sn.status === "ROLLING_BACK";
        const isDehydrated = sn.status === "DEHYDRATED";
        const isHybrid = sn.occupant_type === "HYBRID_TRANSITION";
        const isAgentOccupant = sn.occupant_type === "AGENT";
        const isEmptyShellRoot =
          effectiveNodes.length === 1 && sn.node_type === "BOARD_ROOT";
        const displayTitle = cleanDisplayLabel(sn.label);

        positionedNodes.push({
          id: sn.node_id,
          position: { x: nx, y: ny },
          data: {
            label: (
              <div className="text-left font-sans select-none">
                <div className="flex items-center justify-between gap-1.5 mb-1">
                  <span
                    className="text-[10px] font-medium tracking-wide"
                    style={{
                      color: isDehydrated ? "#67e8f9" : isScouted ? "#9ca3af" : meta.accent,
                    }}
                  >
                    {isEmptyShellRoot ? "初始火种" : meta.tag}
                  </span>
                  {isDehydrated ? (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-400/50">
                      ❄️ 已脱水休眠
                    </span>
                  ) : isScouted ? (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#23262d] text-[#9ca3af] border border-[#374151]">
                      🪨 已探路 · 空壳
                    </span>
                  ) : isHybrid ? (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-950/60 text-amber-300 border border-amber-400/50">
                      ⚡ 人机协同
                      {sn.weave_points.length > 0 ? ` · ${sn.weave_points.length}点` : ""}
                    </span>
                  ) : isAgentOccupant ? (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-400/50">
                      🤖 AI值守
                      {sn.weave_points.length > 0 ? ` · ${sn.weave_points.length}点` : ""}
                    </span>
                  ) : (
                    <span className="text-[10px] px-1.5 py-0.2 rounded bg-[#fbbf24]/15 text-[#fcd34d] border border-[#f59e0b]/40">
                      🔥 已照亮
                      {sn.weave_points.length > 0
                        ? ` · ${sn.weave_points.length}点`
                        : ""}
                    </span>
                  )}
                </div>

                <div
                  className={`text-xs font-medium truncate ${isDehydrated ? "text-cyan-200/80" : isScouted ? "text-[#9ca3af]" : "text-[#f3f4f6]"
                    }`}
                >
                  {displayTitle}
                </div>

                <div className="flex items-center justify-between gap-2 mt-1.5">
                  <span className="text-[10px] text-[#6b7280] truncate">
                    {isDehydrated
                      ? "休眠待命 · 来任务即秒级唤醒"
                      : isScouted
                        ? "仅摸清骨架，待插火把"
                        : sn.weave_points.length > 0
                          ? `已织网 ${sn.weave_points.length} 项能力`
                          : sn.discovered_from || "火种已驻留"}
                  </span>
                  {isScouted && (
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePlantTorch(sn.node_id, "");
                      }}
                      className="shrink-0 px-1.5 py-0.5 rounded bg-[#f59e0b]/20 hover:bg-[#f59e0b]/35 border border-[#f59e0b]/50 text-[#fcd34d] text-[10px] font-medium transition disabled:opacity-40"
                    >
                      🔥 插火把
                    </button>
                  )}
                </div>
              </div>
            ),
          },
          style: {
            width: 224,
            background: isDehydrated
              ? "rgba(8, 51, 68, 0.42)"
              : isScouted
                ? "rgba(21, 23, 27, 0.86)"
                : isAgentOccupant
                  ? "linear-gradient(145deg, #0b2920 0%, #141918 100%)"
                  : "linear-gradient(145deg, #1f1c16 0%, #17181c 100%)",
            backdropFilter: isDehydrated ? "blur(6px)" : undefined,
            border: isAlert
              ? "1.5px solid #f87171"
              : isSelected
                ? "1.5px solid #fde68a"
                : isDehydrated
                  ? "1.5px dashed #22d3ee"
                  : isHybrid
                    ? "1.5px solid #fbbf24"
                    : isAgentOccupant
                      ? "1.5px solid #34d399"
                      : isScouted
                        ? "1.5px dashed #4b5563"
                        : "1.5px solid #f59e0b",
            borderRadius: "10px",
            padding: "9px 11px",
            opacity: isDehydrated ? 0.72 : isScouted ? 0.78 : 1,
            boxShadow: isDehydrated
              ? "0 0 18px rgba(34, 211, 238, 0.16)"
              : isHybrid
                ? "0 0 28px rgba(251, 191, 36, 0.30)"
                : isLit
                  ? isEmptyShellRoot
                    ? "0 0 42px rgba(251, 191, 36, 0.35), 0 0 14px rgba(245, 158, 11, 0.25)"
                    : "0 0 24px rgba(245, 158, 11, 0.18)"
                  : "none",
          },
        });

        // Structural parent -> child edge
        if (sn.parent_id) {
          edges.push({
            id: `e-struct-${sn.parent_id}-${sn.node_id}`,
            source: sn.parent_id,
            target: sn.node_id,
            animated: isLit,
            style: isScouted
              ? {
                stroke: "#4b5563",
                strokeWidth: 1.25,
                strokeDasharray: "6 5",
              }
              : {
                stroke: isAlert ? "#f87171" : "#f59e0b",
                strokeWidth: 1.8,
              },
            markerEnd: {
              type: MarkerType.ArrowClosed,
              color: isScouted ? "#4b5563" : isAlert ? "#f87171" : "#f59e0b",
            },
          });
        }

        // Semantic zoom: expand 2D weave-point satellite nodes when zoomed in, toggled, or selected
        const shouldExpandWeave =
          isLit &&
          sn.weave_points.length > 0 &&
          (zoomLevel >= 1.15 || showAllWeavePoints || isSelected);

        if (shouldExpandWeave) {
          const pts = sn.weave_points;
          const totalPts = pts.length;
          pts.forEach((wp, wpIdx) => {
            const wStyle = WEAVE_TYPE_STYLE[wp.ball_type];
            const angleStart = Math.PI * 0.12;
            const angleEnd = Math.PI * 0.88;
            const angle =
              totalPts === 1
                ? Math.PI * 0.5
                : angleStart + ((angleEnd - angleStart) * wpIdx) / (totalPts - 1);
            const radiusX = 148;
            const radiusY = 86;
            const wx = nx + 38 + Math.cos(angle) * radiusX - (totalPts > 2 ? 32 : 0);
            const wy = ny + 68 + Math.sin(angle) * radiusY;
            const weaveNodeId = `weave-${wp.point_id}`;
            const isWeaveSelected = selectedId === weaveNodeId;

            positionedNodes.push({
              id: weaveNodeId,
              position: { x: wx, y: wy },
              data: {
                label: (
                  <div className="text-left font-sans select-none">
                    <div className="flex items-center justify-between gap-1 mb-0.5">
                      <span
                        className="text-[9px] px-1.5 py-0.2 rounded font-medium"
                        style={{
                          color: wStyle.color,
                          backgroundColor: wStyle.bg,
                          border: `1px solid ${wStyle.border}`,
                        }}
                      >
                        {wStyle.label}
                      </span>
                      {wp.has_executable_tool && (
                        <span className="text-[9px] text-[#34d399]">
                          ⚙ 自动算子
                        </span>
                      )}
                    </div>
                    <div className="text-[11px] font-medium text-[#e5e7eb] truncate">
                      {cleanDisplayLabel(wp.title)}
                    </div>
                  </div>
                ),
              },
              style: {
                width: 158,
                background: "#111318",
                border: isWeaveSelected
                  ? "1.5px solid #fde68a"
                  : `1px solid ${wStyle.border}`,
                borderRadius: "8px",
                padding: "6px 8px",
                boxShadow: "0 4px 14px rgba(0,0,0,0.45)",
              },
            });

            edges.push({
              id: `e-weave-${sn.node_id}-${wp.point_id}`,
              source: sn.node_id,
              target: weaveNodeId,
              style: {
                stroke: wStyle.border,
                strokeWidth: 1.1,
                strokeDasharray: "3 3",
              },
            });
          });
        }
      });
    });

    // Cross-node golden weave edges between LIT nodes
    for (const link of caveMap?.cross_links ?? []) {
      if (
        !posMap.has(link.source_node_id) ||
        !posMap.has(link.target_node_id)
      ) {
        continue;
      }
      edges.push({
        id: link.link_id,
        source: link.source_node_id,
        target: link.target_node_id,
        animated: true,
        label: link.label,
        labelStyle: {
          fill: "#fde68a",
          fontSize: 10,
          fontWeight: 500,
        },
        labelBgStyle: {
          fill: "#181510",
          fillOpacity: 0.9,
        },
        labelBgPadding: [6, 3],
        labelBgBorderRadius: 4,
        style: {
          stroke: "#fbbf24",
          strokeWidth: 2,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: "#fbbf24",
        },
      });
    }

    return { flowNodes: positionedNodes, flowEdges: edges, nodePositions: posMap };
  }, [
    actionBusy,
    caveMap?.cross_links,
    effectiveNodes,
    handlePlantTorch,
    selectedId,
    showAllWeavePoints,
    zoomLevel,
  ]);

  const focusAndZoomNode = useCallback(
    (nodeId: string) => {
      const pos = nodePositions.get(nodeId);
      if (!pos) return;
      setSelectedId(nodeId);
      setShowAllWeavePoints(true);
      setCenter(pos.x + 112, pos.y + 65, { zoom: 1.38, duration: 500 });
    },
    [nodePositions, setCenter]
  );

  const zoomToWeaveOverview = useCallback(() => {
    setShowAllWeavePoints(true);
    const firstLit =
      effectiveNodes.find(
        (n) =>
          n.exploration_state === "LIT" &&
          n.weave_points.length > 0 &&
          n.node_type !== "BOARD_ROOT"
      ) ?? effectiveNodes[0];
    if (firstLit) {
      const pos = nodePositions.get(firstLit.node_id);
      if (pos) {
        setCenter(pos.x + 112, pos.y + 60, { zoom: 1.25, duration: 450 });
        return;
      }
    }
    zoomTo(1.25, { duration: 450 });
  }, [effectiveNodes, nodePositions, setCenter, zoomTo]);

  const mode = caveMap?.mode ?? (effectiveNodes.length <= 1 ? "EMPTY_SHELL" : "FULLY_LIT");
  const stats = caveMap?.stats ?? {
    total_nodes: effectiveNodes.length,
    lit_nodes: effectiveNodes.filter((n) => n.exploration_state !== "SCOUTED").length,
    scouted_nodes: effectiveNodes.filter((n) => n.exploration_state === "SCOUTED").length,
    weave_points_count: effectiveNodes.reduce((acc, n) => acc + n.weave_points.length, 0),
    cross_links_count: caveMap?.cross_links?.length ?? 0,
  };

  return (
    <div className="flex flex-col h-full bg-[#0a0b0e] border border-[#2d2e30] rounded-lg overflow-hidden relative">
      {/* Top Exploration & Weave Header */}
      <div className="px-3.5 py-2 bg-[#141519] border-b border-[#26282e] flex flex-wrap items-center justify-between gap-2 z-20">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-xs font-medium text-[#f3f4f6] flex items-center gap-1.5">
            <Flame className="w-3.5 h-3.5 text-[#fbbf24]" />
            <span>{caveMap?.enterprise_name || "矿洞探索与织网"}</span>
          </span>

          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${mode === "EMPTY_SHELL"
                ? "bg-[#1c1917] border-[#78350f] text-[#fcd34d]"
                : mode === "EXPLORING"
                  ? "bg-[#1f2937] border-[#4b5563] text-[#d1d5db]"
                  : "bg-[#14261c] border-[#10b981]/40 text-[#6ee7b7]"
              }`}
          >
            {mode === "EMPTY_SHELL"
              ? "空瓶壳子 · 等待探路"
              : mode === "EXPLORING"
                ? "矿洞探路中 · 灰暗待驻火"
                : "全网火把已点亮"}
          </span>

          <span className="px-2 py-0.5 rounded bg-[#0d0e12] border border-[#26282e] text-[10px] text-[#9ca3af] flex items-center gap-2">
            <span className="text-[#fcd34d]">🔥 已照亮 {stats.lit_nodes}</span>
            <span>·</span>
            <span className="text-[#9ca3af]">🪨 待驻火 {stats.scouted_nodes}</span>
            <span>·</span>
            <span className="text-[#6ee7b7]">🕸 织网点 {stats.weave_points_count}</span>
            {stats.cross_links_count > 0 && (
              <>
                <span>·</span>
                <span className="text-[#fbbf24]">
                  ⚡ 协作线 {stats.cross_links_count}
                </span>
              </>
            )}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={actionBusy !== null || demoRunning}
            onClick={handleResetEmptyShell}
            className="px-2.5 py-1 rounded bg-[#1f2128] hover:bg-[#2a2d36] border border-[#374151] text-[#d1d5db] text-[11px] flex items-center gap-1 transition disabled:opacity-40"
            title="清空所有预设部门、岗位与规则，回到只剩1个火种的空壳状态"
          >
            <RotateCcw className="w-3 h-3" />
            <span>重置为空壳</span>
          </button>

          <button
            type="button"
            disabled={actionBusy !== null || demoRunning}
            onClick={() => setScoutModalOpen(true)}
            className="px-2.5 py-1 rounded bg-[#f59e0b]/15 hover:bg-[#f59e0b]/25 border border-[#f59e0b]/50 text-[#fcd34d] text-[11px] font-medium flex items-center gap-1 transition disabled:opacity-40"
          >
            <Flashlight className="w-3 h-3" />
            <span>拿火把探路</span>
          </button>

          <button
            type="button"
            disabled={actionBusy !== null && !demoRunning}
            onClick={handleRunAutoPatrol}
            className={`px-2.5 py-1 rounded border text-[11px] font-medium flex items-center gap-1 transition ${demoRunning
                ? "bg-[#7f1d1d]/40 border-[#ef4444]/60 text-[#fca5a5]"
                : "bg-[#064e3b]/60 hover:bg-[#065f46]/70 border-[#10b981]/50 text-[#6ee7b7]"
              } disabled:opacity-40`}
          >
            {demoRunning ? (
              <>
                <Square className="w-3 h-3 fill-current" />
                <span>停止演示</span>
              </>
            ) : (
              <>
                <Sparkles className="w-3 h-3" />
                <span>自动巡洞演示</span>
              </>
            )}
          </button>

          {canControlDrills && (
            <div className="relative">
              <button
                type="button"
                onClick={() => setDrillsOpen((v) => !v)}
                className="px-2 py-1 rounded bg-[#1f2128] hover:bg-[#2a2d36] border border-[#374151] text-[#9ca3af] text-[11px] flex items-center gap-1"
              >
                <span>演练</span>
                <ChevronDown className="w-3 h-3" />
              </button>
              {drillsOpen && (
                <div className="absolute right-0 mt-1 w-36 py-1 rounded-md bg-[#181a20] border border-[#374151] shadow-xl z-30 text-[11px]">
                  <button
                    disabled={busyAction !== null}
                    onClick={() => {
                      setDrillsOpen(false);
                      onDrill("BURST_PAD");
                    }}
                    className="w-full text-left px-3 py-1.5 hover:bg-[#262933] text-[#e5e7eb]"
                  >
                    模拟高峰扩容
                  </button>
                  <button
                    disabled={busyAction !== null}
                    onClick={() => {
                      setDrillsOpen(false);
                      onDrill("BORROW_BALL");
                    }}
                    className="w-full text-left px-3 py-1.5 hover:bg-[#262933] text-[#93c5fd]"
                  >
                    模拟跨组协作
                  </button>
                  <button
                    disabled={busyAction !== null}
                    onClick={() => {
                      setDrillsOpen(false);
                      onDrill("HALLUCINATION_FAULT");
                    }}
                    className="w-full text-left px-3 py-1.5 hover:bg-[#262933] text-[#fca5a5]"
                  >
                    模拟异常恢复
                  </button>
                  <button
                    disabled={busyAction !== null}
                    onClick={() => {
                      setDrillsOpen(false);
                      onDrill("DEHYDRATE_IDLE");
                    }}
                    className="w-full text-left px-3 py-1.5 hover:bg-[#262933] text-[#9ca3af]"
                  >
                    休眠闲置节点
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Live Demo Step Banner */}
      {demoHint && (
        <div className="px-4 py-1.5 bg-[#1c1917] border-b border-[#78350f]/60 text-[11px] text-[#fde68a] flex items-center gap-2 z-20">
          {demoRunning && <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />}
          <span>{demoHint}</span>
        </div>
      )}

      {/* 2D Cave Canvas */}
      <div className="flex-1 relative bg-[#08090c] overflow-hidden">
        {/* Fog-of-War radial vignette overlay */}
        <div
          className="pointer-events-none absolute inset-0 z-[1]"
          style={{
            background:
              mode === "EMPTY_SHELL"
                ? "radial-gradient(circle at 50% 42%, rgba(251,191,36,0.09) 0%, rgba(8,9,12,0.82) 34%, rgba(3,4,6,0.97) 75%)"
                : mode === "EXPLORING"
                  ? "radial-gradient(circle at 50% 45%, rgba(251,191,36,0.06) 0%, rgba(10,12,16,0.52) 58%, rgba(4,5,8,0.88) 100%)"
                  : "radial-gradient(circle at 50% 45%, rgba(251,191,36,0.05) 0%, rgba(10,12,16,0.22) 70%, rgba(5,6,9,0.65) 100%)",
          }}
        />

        {loadingMap ? (
          <div className="h-full flex items-center justify-center text-xs text-[#9ca3af]">
            正在点亮矿洞视图...
          </div>
        ) : (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onMove={(_, viewport: Viewport) => setZoomLevel(viewport.zoom)}
            fitView
            minZoom={0.25}
            maxZoom={2.6}
          >
            <Background color="#1d2028" gap={24} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        )}

        {/* Empty Shell Onboarding Banner */}
        {mode === "EMPTY_SHELL" && !demoRunning && (
          <div className="absolute bottom-14 left-1/2 -translate-x-1/2 z-10 w-[92%] max-w-lg p-3.5 rounded-xl bg-[#13141a]/95 border border-[#78350f]/70 shadow-2xl text-center space-y-2 backdrop-blur">
            <div className="text-xs font-medium text-[#fde68a]">
              当前是「空瓶壳子」：四周一片未知黑暗，仅中央有 1 颗初始火种
            </div>
            <div className="text-[11px] text-[#9ca3af] leading-relaxed">
              先喂入真实的企业介绍或部门分工，让 Agent 拿火把去探出灰色组织轮廓；再选择想要落地的岗位插下常驻火把，照亮业务规则并织网。
            </div>
            <div className="pt-1 flex items-center justify-center gap-2">
              <button
                type="button"
                onClick={() => setScoutModalOpen(true)}
                className="px-3 py-1.5 rounded-md bg-[#f59e0b] hover:bg-[#d97706] text-[#111827] text-xs font-medium flex items-center gap-1.5 transition"
              >
                <Flashlight className="w-3.5 h-3.5" />
                <span>喂入企业资料 · 拿火把探路</span>
              </button>
              <button
                type="button"
                onClick={handleRunAutoPatrol}
                className="px-3 py-1.5 rounded-md bg-[#1f2937] hover:bg-[#374151] border border-[#4b5563] text-[#e5e7eb] text-xs flex items-center gap-1.5 transition"
              >
                <Sparkles className="w-3.5 h-3.5 text-[#6ee7b7]" />
                <span>看一遍自动探路织网</span>
              </button>
            </div>
          </div>
        )}

        {/* Bottom-left Zoom & Semantic Weave Points Control Bar */}
        <div className="absolute bottom-3 left-14 z-10 flex flex-wrap items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[#14161c]/90 border border-[#2d313b] text-[11px] backdrop-blur">
          <span className="text-[#9ca3af] font-mono pr-1">
            缩放 {Math.round(zoomLevel * 100)}%
          </span>
          <button
            type="button"
            onClick={() => fitView({ padding: 0.22, duration: 420 })}
            className="px-2 py-0.5 rounded bg-[#1f222b] hover:bg-[#2b2f3a] text-[#d1d5db] flex items-center gap-1"
          >
            <Maximize2 className="w-3 h-3" />
            <span>俯瞰全图</span>
          </button>
          <button
            type="button"
            onClick={zoomToWeaveOverview}
            className="px-2 py-0.5 rounded bg-[#1f222b] hover:bg-[#2b2f3a] text-[#fcd34d] flex items-center gap-1"
          >
            <ZoomIn className="w-3 h-3" />
            <span>放大看织网点</span>
          </button>
          <button
            type="button"
            onClick={() => setShowAllWeavePoints((v) => !v)}
            className={`px-2 py-0.5 rounded flex items-center gap-1 border ${showAllWeavePoints || zoomLevel >= 1.15
                ? "bg-[#064e3b]/50 border-[#10b981]/50 text-[#6ee7b7]"
                : "bg-[#1f222b] border-transparent text-[#9ca3af] hover:text-[#e5e7eb]"
              }`}
          >
            {showAllWeavePoints || zoomLevel >= 1.15 ? (
              <Eye className="w-3 h-3" />
            ) : (
              <EyeOff className="w-3 h-3" />
            )}
            <span>
              {showAllWeavePoints || zoomLevel >= 1.15
                ? "织网点已展开"
                : "展开全部织网点"}
            </span>
          </button>
        </div>

        {/* Right Inspector Drawer: Gray SCOUTED node / LIT node / Weave Point micro-node */}
        {selectedCaveNode && (
          <div className="absolute top-3 right-3 bottom-3 w-96 max-w-[calc(100%-24px)] rounded-xl bg-[#14161c]/95 backdrop-blur border border-[#374151] shadow-2xl z-20 flex flex-col overflow-hidden text-xs">
            <div className="px-3.5 py-2.5 border-b border-[#26282e] flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${selectedCaveNode.exploration_state === "SCOUTED"
                      ? "bg-[#23262d] text-[#9ca3af]"
                      : "bg-[#f59e0b]/20 text-[#fcd34d]"
                    }`}
                >
                  {selectedCaveNode.exploration_state === "SCOUTED"
                    ? "🪨 已探路(灰)"
                    : "🔥 已插火把"}
                </span>
                <span className="text-[11px] text-[#9ca3af] truncate">
                  {NODE_META_BY_TYPE[selectedCaveNode.node_type].tag}
                </span>
              </div>
              <button
                onClick={() => setSelectedId(null)}
                className="text-[#9ca3af] hover:text-[#f3f4f6] p-0.5"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-3.5 space-y-3">
              <div>
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium text-[#f3f4f6]">
                    {cleanDisplayLabel(selectedCaveNode.label)}
                  </div>
                  {selectedCaveNode.status === "DEHYDRATED" && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/70 text-cyan-300 border border-cyan-400/50 shrink-0">
                      ❄️ DEHYDRATED
                    </span>
                  )}
                </div>
                {(selectedCaveNode.department || selectedCaveNode.occupant_title) && (
                  <div className="text-[11px] text-[#9ca3af] mt-0.5">
                    {[selectedCaveNode.department, selectedCaveNode.occupant_title, selectedCaveNode.occupant_type]
                      .filter(Boolean)
                      .join(" · ")}
                  </div>
                )}
                {canControlDrills && selectedCaveNode.node_type !== "BOARD_ROOT" && (
                  <div className="mt-2">
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={async () => {
                        const targetAction =
                          selectedCaveNode.status === "DEHYDRATED" ? "REHYDRATE" : "DEHYDRATE";
                        setActionBusy(`lifecycle:${selectedCaveNode.node_id}`);
                        try {
                          await toggleSpiderNodeLifecycle({
                            nodeId: selectedCaveNode.node_id,
                            action: targetAction,
                            role_view: "boss",
                            reason:
                              targetAction === "DEHYDRATE"
                                ? "管理员手动脱水休眠"
                                : "管理员手动热唤醒恢复",
                          });
                          onToast?.(
                            targetAction === "DEHYDRATE"
                              ? `❄️ 已脱水休眠节点：${cleanDisplayLabel(selectedCaveNode.label)}`
                              : `⚡ 已级联热唤醒节点：${cleanDisplayLabel(selectedCaveNode.label)}`
                          );
                          await loadCaveMap();
                          await onRefreshAll?.();
                        } catch (err) {
                          onToast?.(
                            err instanceof Error ? err.message : "生命周期切换失败",
                            "err"
                          );
                        } finally {
                          setActionBusy(null);
                        }
                      }}
                      className={`w-full py-1.5 rounded-md text-[11px] font-medium border flex items-center justify-center gap-1.5 transition disabled:opacity-40 ${
                        selectedCaveNode.status === "DEHYDRATED"
                          ? "bg-amber-500/20 hover:bg-amber-500/30 border-amber-400/50 text-amber-200"
                          : "bg-cyan-950/60 hover:bg-cyan-900/60 border-cyan-500/50 text-cyan-200"
                      }`}
                    >
                      {selectedCaveNode.status === "DEHYDRATED"
                        ? "⚡ 立即级联热唤醒 (REHYDRATE)"
                        : "❄️ 强制脱水休眠 (DEHYDRATE)"}
                    </button>
                  </div>
                )}
              </div>

              {selectedCaveNode.exploration_state === "SCOUTED" ? (
                <div className="space-y-3">
                  <div className="p-2.5 rounded-lg bg-[#1b1d24] border border-dashed border-[#4b5563] text-[11px] text-[#d1d5db] leading-relaxed">
                    这处区域刚被火把探出轮廓——我们知道了公司里有这个岗位，但火把拿走后这里还是灰色的空壳，尚未沉淀具体规则或工具。
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-[11px] text-[#9ca3af] block">
                      补充该岗位的真实制度 / 报价规则（可留空，由 Agent 自主推演）
                    </label>
                    <textarea
                      value={sopDraft}
                      onChange={(e) => setSopDraft(e.target.value)}
                      rows={4}
                      placeholder="例如：首重3公斤内10元，超重每公斤加4元，满500元免运费；低于8.5折必须组长审批；严禁透出真实成本底价。"
                      className="w-full rounded-lg bg-[#0d0e12] border border-[#374151] px-2.5 py-2 text-[11px] text-[#f3f4f6] placeholder:text-[#4b5563] focus:outline-none focus:border-[#f59e0b]"
                    />
                  </div>

                  <button
                    type="button"
                    disabled={actionBusy !== null}
                    onClick={() => handlePlantTorch(selectedCaveNode.node_id)}
                    className="w-full py-2 rounded-lg bg-[#f59e0b] hover:bg-[#d97706] text-[#111827] font-medium text-xs flex items-center justify-center gap-1.5 transition disabled:opacity-40"
                  >
                    {actionBusy === `torch:${selectedCaveNode.node_id}` ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Flame className="w-3.5 h-3.5" />
                    )}
                    <span>在此插下火把（照亮并织网）</span>
                  </button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => focusAndZoomNode(selectedCaveNode.node_id)}
                      className="flex-1 py-1.5 px-2.5 rounded-md bg-[#1f2937] hover:bg-[#374151] border border-[#4b5563] text-[#fcd34d] text-[11px] flex items-center justify-center gap-1.5"
                    >
                      <ZoomIn className="w-3.5 h-3.5" />
                      <span>推近放大查看织网点</span>
                    </button>
                  </div>

                  {/* Woven Points List */}
                  <div className="space-y-1.5">
                    <div className="text-[11px] text-[#9ca3af] flex items-center justify-between">
                      <span>已照亮的织网点</span>
                      <span>{selectedCaveNode.weave_points.length} 项</span>
                    </div>
                    {selectedCaveNode.weave_points.length === 0 ? (
                      <div className="p-2.5 rounded-lg bg-[#101217] border border-[#26282e] text-[11px] text-[#6b7280]">
                        当前节点为初始火种中枢或尚未追加细则，可在下方补充制度继续织网。
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        {selectedCaveNode.weave_points.map((wp) => {
                          const ws = WEAVE_TYPE_STYLE[wp.ball_type];
                          return (
                            <div
                              key={wp.point_id}
                              onClick={() => setSelectedId(`weave-${wp.point_id}`)}
                              className="p-2.5 rounded-lg bg-[#0d0e12] hover:bg-[#161922] border border-[#26282e] cursor-pointer space-y-1 transition"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <span
                                  className="text-[10px] px-1.5 py-0.2 rounded"
                                  style={{
                                    color: ws.color,
                                    backgroundColor: ws.bg,
                                    border: `1px solid ${ws.border}`,
                                  }}
                                >
                                  {ws.label}
                                </span>
                                {wp.has_executable_tool && (
                                  <span className="text-[10px] text-[#34d399]">
                                    ⚙ 可自动运算
                                  </span>
                                )}
                              </div>
                              <div className="text-xs font-medium text-[#e5e7eb]">
                                {cleanDisplayLabel(wp.title)}
                              </div>
                              <div className="text-[11px] text-[#9ca3af] line-clamp-2">
                                {wp.summary}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* Additional weave input */}
                  <div className="pt-2 border-t border-[#26282e] space-y-1.5">
                    <label className="text-[11px] text-[#9ca3af] block">
                      继续喂入新规则，在此节点新增织网点
                    </label>
                    <textarea
                      value={sopDraft}
                      onChange={(e) => setSopDraft(e.target.value)}
                      rows={3}
                      placeholder="粘贴一段新制度、折扣表或风控条款..."
                      className="w-full rounded-lg bg-[#0d0e12] border border-[#374151] px-2.5 py-2 text-[11px] text-[#f3f4f6] placeholder:text-[#4b5563] focus:outline-none focus:border-[#f59e0b]"
                    />
                    <button
                      type="button"
                      disabled={actionBusy !== null}
                      onClick={() => handlePlantTorch(selectedCaveNode.node_id)}
                      className="w-full py-1.5 rounded-md bg-[#f59e0b]/20 hover:bg-[#f59e0b]/30 border border-[#f59e0b]/50 text-[#fcd34d] text-[11px] font-medium flex items-center justify-center gap-1.5 disabled:opacity-40"
                    >
                      {actionBusy === `torch:${selectedCaveNode.node_id}` ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Flame className="w-3 h-3" />
                      )}
                      <span>追加照亮并织网</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {selectedWeavePoint && (
          <div className="absolute top-3 right-3 w-96 max-w-[calc(100%-24px)] rounded-xl bg-[#14161c]/95 backdrop-blur border border-[#374151] shadow-2xl z-20 p-3.5 space-y-3 text-xs">
            <div className="flex items-center justify-between border-b border-[#26282e] pb-2">
              <div className="flex items-center gap-2">
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                  style={{
                    color: WEAVE_TYPE_STYLE[selectedWeavePoint.point.ball_type].color,
                    backgroundColor:
                      WEAVE_TYPE_STYLE[selectedWeavePoint.point.ball_type].bg,
                    border: `1px solid ${WEAVE_TYPE_STYLE[selectedWeavePoint.point.ball_type].border
                      }`,
                  }}
                >
                  {selectedWeavePoint.point.type_label}
                </span>
                <span className="text-[11px] text-[#9ca3af] truncate">
                  归属：{cleanDisplayLabel(selectedWeavePoint.hostNode.label)}
                </span>
              </div>
              <button
                onClick={() =>
                  setSelectedId(selectedWeavePoint.hostNode.node_id)
                }
                className="text-[#9ca3af] hover:text-[#f3f4f6] text-[11px]"
              >
                返回岗位
              </button>
            </div>

            <div className="text-sm font-medium text-[#f3f4f6]">
              {cleanDisplayLabel(selectedWeavePoint.point.title)}
            </div>

            <div className="p-2.5 rounded-lg bg-[#0d0e12] border border-[#26282e] text-[11px] text-[#d1d5db] leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap">
              {selectedWeavePoint.point.content}
            </div>

            {selectedWeavePoint.point.domain_tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {selectedWeavePoint.point.domain_tags.map((t) => (
                  <span
                    key={t}
                    className="px-1.5 py-0.5 rounded bg-[#1f222b] text-[#9ca3af] text-[10px]"
                  >
                    #{t}
                  </span>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2 pt-1">
              {onQuickUse && (
                <button
                  type="button"
                  onClick={() =>
                    onQuickUse(
                      selectedWeavePoint.point.quick_use_prompt,
                      selectedWeavePoint.point.ball_type
                    )
                  }
                  className="flex-1 py-2 rounded-lg bg-[#2563eb] hover:bg-[#1d4ed8] text-white text-xs font-medium flex items-center justify-center gap-1.5"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  <span>去工作对话试用</span>
                </button>
              )}
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="px-3 py-2 rounded-lg bg-[#1f222b] hover:bg-[#2b2f3a] text-[#d1d5db] text-xs"
              >
                关闭
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Scout Organization Modal */}
      {scoutModalOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleScoutSubmit}
            className="w-full max-w-xl rounded-xl bg-[#16181f] border border-[#374151] shadow-2xl overflow-hidden text-xs"
          >
            <div className="px-4 py-3 border-b border-[#26282e] flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-[#fde68a]">
                <Flashlight className="w-4 h-4 text-[#fbbf24]" />
                <span>拿火把探路 · 摸清真实机构骨架</span>
              </div>
              <button
                type="button"
                onClick={() => setScoutModalOpen(false)}
                className="text-[#9ca3af] hover:text-[#f3f4f6]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-4 space-y-3">
              <div className="text-[11px] text-[#9ca3af] leading-relaxed">
                这一步只负责「拿火把探出公司有哪些部门和岗位路子」，探出来的节点会先呈现为
                <span className="text-[#d1d5db] font-medium">灰色空壳</span>
                ——之后你可以按需挑选任意岗位插下火把，再把具体规则与工具织进去。
              </div>

              {(caveMap?.starter_dossiers?.length ?? 0) > 0 && (
                <div className="space-y-1.5">
                  <div className="text-[11px] text-[#9ca3af]">
                    一键填入真实企业资料小样：
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {caveMap?.starter_dossiers.map((d) => (
                      <button
                        key={d.dossier_id}
                        type="button"
                        onClick={() => {
                          setScoutName(d.enterprise_name);
                          setScoutMaterial(d.raw_org_material);
                        }}
                        className={`px-2.5 py-1 rounded-md border text-[11px] transition ${scoutName === d.enterprise_name
                            ? "bg-[#f59e0b]/20 border-[#f59e0b] text-[#fcd34d]"
                            : "bg-[#1f222b] border-[#374151] text-[#d1d5db] hover:border-[#6b7280]"
                          }`}
                      >
                        {d.enterprise_name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="space-y-1">
                <label className="text-[11px] text-[#9ca3af] block">
                  企业名称
                </label>
                <input
                  value={scoutName}
                  onChange={(e) => setScoutName(e.target.value)}
                  className="w-full rounded-lg bg-[#0d0e12] border border-[#374151] px-3 py-2 text-xs text-[#f3f4f6] focus:outline-none focus:border-[#f59e0b]"
                  placeholder="输入要探索的真实公司名称"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] text-[#9ca3af] block">
                  企业背景与组织分工描述
                </label>
                <textarea
                  value={scoutMaterial}
                  onChange={(e) => setScoutMaterial(e.target.value)}
                  rows={6}
                  className="w-full rounded-lg bg-[#0d0e12] border border-[#374151] px-3 py-2 text-[11px] text-[#f3f4f6] leading-relaxed focus:outline-none focus:border-[#f59e0b]"
                  placeholder="粘贴公司简介、部门列表、岗位职责说明或聊天架构片段..."
                />
              </div>
            </div>

            <div className="px-4 py-3 bg-[#111318] border-t border-[#26282e] flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setScoutModalOpen(false)}
                className="px-3 py-1.5 rounded-md bg-[#1f222b] text-[#d1d5db] hover:bg-[#2a2e39]"
              >
                取消
              </button>
              <button
                type="submit"
                disabled={actionBusy === "scout"}
                className="px-4 py-1.5 rounded-md bg-[#f59e0b] hover:bg-[#d97706] text-[#111827] font-medium flex items-center gap-1.5 disabled:opacity-40"
              >
                {actionBusy === "scout" ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Flashlight className="w-3.5 h-3.5" />
                )}
                <span>开始火把探路</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

export const SpiderTopologyFlow: React.FC<Props> = (props) => {
  return (
    <ReactFlowProvider>
      <SpiderTopologyFlowInner {...props} />
    </ReactFlowProvider>
  );
};
