import React, { useEffect, useMemo, useState } from "react";
import {
  Archive,
  Building2,
  CheckCircle2,
  Clock,
  Database,
  HardDrive,
  History,
  Layers,
  Loader2,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Table,
  Terminal,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import {
  deleteClusterSnapshot,
  fetchClusterSnapshots,
  fetchIngestSamples,
  ingestEnterpriseDocument,
  restoreClusterSnapshot,
  saveClusterSnapshot,
} from "../api";
import {
  AccountDirectoryEntry,
  ClusterSnapshotMetadata,
  CustodyOverviewPayload,
  EnterpriseDocumentIngestResponse,
  EnterpriseIngestSampleItem,
  UnifiedOverviewPayload,
  UnitSlot,
} from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  account: AccountDirectoryEntry;
  overview: UnifiedOverviewPayload | null;
  custody: CustodyOverviewPayload | null;
  onClusterMutated: () => Promise<void>;
  onToast: (text: string, kind?: "ok" | "err") => void;
}

type StudioTab = "document_ingestor" | "snapshot_timemachine";

const FALLBACK_INGEST_SAMPLES: EnterpriseIngestSampleItem[] = [
  {
    sample_id: "sample_csv_steel_ledger",
    doc_title: "2026Q4 特种合金钢阶梯价格与全国分仓安全库存台账",
    doc_format: "CSV",
    target_department: "供应链与销售部",
    target_slot_id: "slot_sales_01",
    description:
      "包含6大特钢牌号的基础吨价、50吨/200吨阶梯折扣系数、保底毛利率红线与华东/华南/西南分仓实时库存水位",
    raw_content: `sku_code,material_name,spec_grade,base_price_cny_per_ton,tier_50t_discount,tier_200t_discount,min_margin_redline,stock_tons_east,stock_tons_south,lead_time_days
ST-316L-01,医用级超低碳奥氏体不锈钢棒,ASTM_316LVM,28500,0.96,0.92,0.18,145,80,3
ST-TI64-02,航空级钛合金精密锻件坯料,TC4_ELI,168000,0.95,0.90,0.22,32,18,7
ST-IN718-03,高温镍基合金涡轮盘毛坯,GH4169,245000,0.97,0.93,0.25,19,12,10
ST-42CR-04,风电主轴高强合金结构钢,42CrMo4,8900,0.94,0.89,0.15,520,310,2
ST-H13-05,精密压铸热作模具钢模块,NADCA_207,19600,0.95,0.91,0.17,210,130,4`,
  },
  {
    sample_id: "sample_json_ev_bom",
    doc_title: "800V碳化硅电驱系统核心BOM采购清单与供应商准入规范",
    doc_format: "JSON",
    target_department: "研发与采购中心",
    target_slot_id: "slot_leader_01",
    description:
      "ERP导出的新能源汽车800V电驱总成BOM结构、单套定额成本、独家芯片断供备选切换阈值及采购特批权限规则",
    raw_content: JSON.stringify(
      {
        assembly_code: "EDU-800V-SIC-PRO",
        assembly_name: "800V双电机碳化硅电驱桥总成",
        target_bom_cost_cny: 11850.0,
        approval_rules: {
          spot_buy_premium_limit_ratio: 0.08,
          single_po_leader_limit_cny: 250000,
          director_co_sign_threshold_cny: 1000000,
        },
        redlines: [
          "严禁采购未通过AEC-Q101车规级认证的SiC晶圆批次",
          "严禁向二级贸易商泄露主机厂年度阶梯年降(3.5%/Q)底盘协议",
        ],
        bom_items: [
          {
            part_no: "SIC-MOS-1200V",
            part_name: "1200V车规级碳化硅功率模块",
            qty_per_set: 6,
            unit_cost_cny: 980.0,
            safety_stock_sets: 500,
            tier1_vendor: "安森美/芯联专供",
          },
          {
            part_no: "HAIRPIN-STATOR-09",
            part_name: "8层扁线油冷定子总成",
            qty_per_set: 1,
            unit_cost_cny: 2150.0,
            safety_stock_sets: 300,
            tier1_vendor: "精进智造",
          },
          {
            part_no: "RESOLVER-ASIL-D",
            part_name: "双冗余旋变位置传感器",
            qty_per_set: 2,
            unit_cost_cny: 340.0,
            safety_stock_sets: 800,
            tier1_vendor: "多摩川精密",
          },
        ],
      },
      null,
      2
    ),
  },
  {
    sample_id: "sample_md_dealer_contract",
    doc_title: "2026年度省级核心经销商阶梯返利与断供违约金主合同",
    doc_format: "CONTRACT_MD",
    target_department: "法务与财务风控部",
    target_slot_id: "slot_finance_01",
    description:
      "涵盖季度提货阶梯返点核算公式、延误交付日违约金计算方法、授信账期审批权限边界及反商业贿赂与防窜货红线",
    raw_content: `# 2026年度省级核心经销商战略合作与风控主合同

## 第一条：季度提货额阶梯返利核算公式 (SKILL & DATA)
1. 季度实际回款提货额 < 300 万元：不享受阶梯返利（返利比例 0%）；
2. 季度回款提货额在 300 万元（含）至 800 万元之间：按全额的 3.5% 计提季度货款抵扣券；
3. 季度回款提货额 ≥ 800 万元：基础返利 3.5%，且超出 800 万元部分额外奖励 6.0% 阶梯返利；
4. 紧急加急冷链/专车配送费：距离 ≤ 500km 按 1200 元/车收取；超出 500km 部分按 2.2 元/公里累加。

## 第二条：交付延误违约金与赔付上限 (SKILL)
1. 若因卖方排产或物流原因导致逾期交货超过 48 小时，每逾期 1 天，按逾期批次货值的 0.4% 计提履约违约金；
2. 单笔订单累计逾期违约金总额最高不得超过该批次合同总额的 12.0%。

## 第三条：授信账期与折扣特批权限边界 (AUTHORITY)
1. 标准现汇结算或 30 天以内银行承兑汇票：由一线商务专员直接核准放行；
2. 申请 31~60 天授信账期，或单笔促销折让在 5.0%~10.0% 之间：必须经大区业务组长审批；
3. 申请超过 60 天账期，或单笔折让超过 10.0%：必须提交财务总监与总办联签。

## 第四条：零容忍合规与防窜货高压红线 (REDLINE)
1. 【防窜货红线】严禁经销商跨省低价倾销或涂改产品唯一追溯激光码，违者立即冻结全额返利并扣除 50 万元履约保证金；
2. 【税务与底价红线】严禁通过拆分合同逃避单笔审批阈值、严禁开具无真实货物交易的虚开发票、严禁向外部透露集团出厂净毛利底线（≥18%）。`,
  },
];

const FALLBACK_SLOTS: UnitSlot[] = [
  {
    slot_id: "slot_sales_01",
    slot_name: "一线业务与跟单工位",
    department: "销售业务部",
    ball_ids: [],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "role_frontline_01",
  },
  {
    slot_id: "slot_leader_01",
    slot_name: "基层业务主管工位",
    department: "销售管理部",
    ball_ids: [],
    borrowed_balls: [],
    occupant_type: "HYBRID_TRANSITION",
    occupant_id: "role_leader_01",
  },
  {
    slot_id: "slot_finance_01",
    slot_name: "财务风控与核算工位",
    department: "财务风控部",
    ball_ids: [],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "role_finance_01",
  },
  {
    slot_id: "slot_manager_01",
    slot_name: "部门运营中枢主管工位",
    department: "运营管理部",
    ball_ids: [],
    borrowed_balls: [],
    occupant_type: "HYBRID_TRANSITION",
    occupant_id: "role_manager_01",
  },
  {
    slot_id: "slot_boss_01",
    slot_name: "顶层总办与董事会席位",
    department: "总办董事会",
    ball_ids: [],
    borrowed_balls: [],
    occupant_type: "HUMAN",
    occupant_id: "role_boss_01",
  },
];

function normalizeIngestSamples(raw: unknown): EnterpriseIngestSampleItem[] {
  const list = Array.isArray(raw)
    ? raw
    : raw &&
      typeof raw === "object" &&
      Array.isArray((raw as { samples?: unknown[] }).samples)
      ? (raw as { samples: unknown[] }).samples
      : [];

  const parsed: EnterpriseIngestSampleItem[] = [];
  list.forEach((item, idx) => {
    if (!item || typeof item !== "object") return;
    const obj = item as Record<string, unknown>;
    const doc_title = String(
      obj.doc_title ?? obj.title ?? obj.name ?? `企业数据样本 #${idx + 1}`
    );
    const raw_content = String(
      obj.raw_content ?? obj.content ?? obj.text ?? ""
    );
    if (!raw_content) return;
    parsed.push({
      sample_id: String(obj.sample_id ?? obj.id ?? `sample_${idx}`),
      doc_title,
      doc_format: String(obj.doc_format ?? obj.format ?? "AUTO"),
      target_department: String(
        obj.target_department ?? obj.department ?? "核心业务部"
      ),
      target_slot_id: obj.target_slot_id
        ? String(obj.target_slot_id)
        : undefined,
      description: obj.description ? String(obj.description) : undefined,
      raw_content,
    });
  });

  return parsed.length > 0 ? parsed : FALLBACK_INGEST_SAMPLES;
}

function normalizeSnapshotsList(raw: unknown): ClusterSnapshotMetadata[] {
  const list = Array.isArray(raw)
    ? raw
    : raw &&
      typeof raw === "object" &&
      Array.isArray((raw as { snapshots?: unknown[] }).snapshots)
      ? (raw as { snapshots: unknown[] }).snapshots
      : [];

  return list
    .filter((item): item is Record<string, unknown> =>
      Boolean(item && typeof item === "object")
    )
    .map((obj, idx) => ({
      snapshot_id: String(obj.snapshot_id ?? obj.id ?? `snap_${idx}`),
      label: String(obj.label ?? obj.name ?? `集群快照 #${idx + 1}`),
      note: obj.note ? String(obj.note) : undefined,
      enterprise_name: obj.enterprise_name ? String(obj.enterprise_name) : undefined,
      workspace_mode: obj.workspace_mode ? String(obj.workspace_mode) : undefined,
      created_at: String(obj.created_at ?? obj.timestamp ?? ""),
      stats:
        obj.stats && typeof obj.stats === "object"
          ? (obj.stats as ClusterSnapshotMetadata["stats"])
          : undefined,
      head_hash: obj.head_hash
        ? String(obj.head_hash)
        : obj.worm_head_hash
          ? String(obj.worm_head_hash)
          : undefined,
    }));
}

export const EnterpriseIngestSnapshotModal: React.FC<Props> = ({
  open,
  onClose,
  account,
  overview,
  onClusterMutated,
  onToast,
}) => {
  const [activeTab, setActiveTab] = useState<StudioTab>("document_ingestor");

  // Available Slots
  const availableSlots = useMemo<UnitSlot[]>(() => {
    const map = new Map<string, UnitSlot>();
    for (const s of overview?.all_slots ?? []) {
      map.set(s.slot_id, s);
    }
    if (overview?.my_slot && !map.has(overview.my_slot.slot_id)) {
      map.set(overview.my_slot.slot_id, overview.my_slot);
    }
    for (const fb of FALLBACK_SLOTS) {
      if (!map.has(fb.slot_id)) {
        map.set(fb.slot_id, fb);
      }
    }
    return Array.from(map.values());
  }, [overview]);

  // Tab 1 State: Document Ingestor
  const [samples, setSamples] = useState<EnterpriseIngestSampleItem[]>(
    FALLBACK_INGEST_SAMPLES
  );
  const [loadingSamples, setLoadingSamples] = useState(false);
  const [docTitle, setDocTitle] = useState(
    FALLBACK_INGEST_SAMPLES[0].doc_title
  );
  const [docFormat, setDocFormat] = useState<
    "CSV" | "JSON" | "CONTRACT_MD" | "AUTO"
  >("CSV");
  const [targetDepartment, setTargetDepartment] = useState(
    FALLBACK_INGEST_SAMPLES[0].target_department
  );
  const [targetSlotId, setTargetSlotId] = useState<string>(account.slot_id);
  const [rawContent, setRawContent] = useState(
    FALLBACK_INGEST_SAMPLES[0].raw_content
  );
  const [autoForgeSkill, setAutoForgeSkill] = useState<boolean>(true);
  const [ingesting, setIngesting] = useState<boolean>(false);
  const [ingestResult, setIngestResult] =
    useState<EnterpriseDocumentIngestResponse | null>(null);

  // Tab 2 State: Snapshot Time-Machine
  const [snapshots, setSnapshots] = useState<ClusterSnapshotMetadata[]>([]);
  const [loadingSnapshots, setLoadingSnapshots] = useState<boolean>(false);
  const [snapshotLabel, setSnapshotLabel] = useState<string>(
    "生产集群全量状态快照"
  );
  const [snapshotNote, setSnapshotNote] = useState<string>(
    "多企业组织架构、工位权能球、外部连接器与 WORM 审计链全量快照"
  );
  const [savingSnapshot, setSavingSnapshot] = useState<boolean>(false);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadSnapshots = async () => {
    setLoadingSnapshots(true);
    try {
      const raw = await fetchClusterSnapshots();
      setSnapshots(normalizeSnapshotsList(raw));
    } catch {
      // ignore
    } finally {
      setLoadingSnapshots(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingSamples(true);
    fetchIngestSamples()
      .then((raw) => {
        if (cancelled) return;
        setSamples(normalizeIngestSamples(raw));
      })
      .catch(() => {
        if (!cancelled) setSamples(FALLBACK_INGEST_SAMPLES);
      })
      .finally(() => {
        if (!cancelled) setLoadingSamples(false);
      });

    loadSnapshots();
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  const handleIngestDocument = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docTitle.trim() || !rawContent.trim() || ingesting) return;
    setIngesting(true);
    try {
      const res = await ingestEnterpriseDocument({
        doc_title: docTitle.trim(),
        doc_format: docFormat,
        raw_content: rawContent,
        target_department: targetDepartment.trim() || "核心业务部",
        target_slot_id: targetSlotId || null,
        auto_forge_query_skill: autoForgeSkill,
      });
      setIngestResult(res);
      await onClusterMutated();
      onToast(
        `📥 深度吞噬完成！已从「${res.doc_title}」编译生成 ${res.created_balls?.length ?? 0
        } 颗可执行能力球并完成沙箱实测`,
        "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "企业文档/台账深度吞噬失败",
        "err"
      );
    } finally {
      setIngesting(false);
    }
  };

  const handleSaveSnapshot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!snapshotLabel.trim() || savingSnapshot) return;
    setSavingSnapshot(true);
    try {
      const created = await saveClusterSnapshot({
        label: snapshotLabel.trim(),
        note: snapshotNote.trim(),
      });
      await loadSnapshots();
      onToast(
        `⏱️ 集群快照「${created.label || snapshotLabel}」已持久化写入磁盘！`,
        "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "保存集群快照失败",
        "err"
      );
    } finally {
      setSavingSnapshot(false);
    }
  };

  const handleRestoreSnapshot = async (snap: ClusterSnapshotMetadata) => {
    if (restoringId || deletingId) return;
    setRestoringId(snap.snapshot_id);
    try {
      const res = await restoreClusterSnapshot({
        snapshot_id: snap.snapshot_id,
      });
      await onClusterMutated();
      await loadSnapshots();
      onToast(
        res.message ??
        res.summary ??
        `⏪ 时间机器回滚成功！全站集群已恢复至快照「${snap.label}」状态`,
        "ok"
      );
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "回滚恢复集群快照失败",
        "err"
      );
    } finally {
      setRestoringId(null);
    }
  };

  const handleDeleteSnapshot = async (snap: ClusterSnapshotMetadata) => {
    if (restoringId || deletingId) return;
    setDeletingId(snap.snapshot_id);
    try {
      await deleteClusterSnapshot(snap.snapshot_id);
      await loadSnapshots();
      onToast(`🗑️ 已删除集群快照「${snap.label}」`, "ok");
    } catch (err: unknown) {
      onToast(
        err instanceof Error ? err.message : "删除集群快照失败",
        "err"
      );
    } finally {
      setDeletingId(null);
    }
  };

  const ballTypeBadge = (ballType: string) => {
    switch (ballType) {
      case "DATA":
        return "bg-[#a8c7fa]/15 text-[#a8c7fa] border-[#a8c7fa]/40";
      case "SKILL":
        return "bg-[#81c995]/15 text-[#81c995] border-[#81c995]/40";
      case "AUTHORITY":
        return "bg-[#fdd663]/15 text-[#fdd663] border-[#fdd663]/40";
      case "REDLINE":
        return "bg-[#f28b82]/15 text-[#f28b82] border-[#f28b82]/40";
      default:
        return "bg-[#282a2c] text-[#e3e3e3] border-[#3c4043]";
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#131314] border border-[#2d2e30] rounded-xl w-full max-w-6xl max-h-[92vh] flex flex-col shadow-2xl overflow-hidden text-xs text-[#e3e3e3]">
        {/* Header */}
        <div className="px-5 py-3.5 bg-[#18191b] border-b border-[#2d2e30] flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#81c995]/15 border border-[#81c995]/40 flex items-center justify-center text-[#81c995]">
              <Database className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold text-[#e3e3e3]">
                  企业表格/合同深度吞噬器 &amp; 集群快照时间机器 (Enterprise Ingestor
                  &amp; Time-Machine)
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995] border border-[#81c995]/30">
                  Pillar 3 · Multimodal Ingest &amp; Snapshots v5.0
                </span>
              </div>
              <p className="text-[11px] text-[#9aa0a6] mt-0.5">
                一键吞噬真实 CSV 台账、ERP BOM JSON 与法务主合同并自动锻造可查表计价的
                Python 技能球；支持全量集群磁盘快照与一键时间回滚
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] font-mono text-[11px] text-[#9aa0a6] flex items-center gap-1.5">
              <HardDrive className="w-3.5 h-3.5 text-[#81c995]" />
              <span>磁盘快照点: {snapshots.length} 个</span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-[#282a2c] text-[#9aa0a6] hover:text-[#e3e3e3] transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Studio Mode Tabs */}
        <div className="px-5 py-2.5 bg-[#18191b]/60 border-b border-[#2d2e30] flex flex-wrap items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("document_ingestor")}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "document_ingestor"
                ? "bg-[#81c995] text-[#0d3b1e] border-[#81c995] shadow-sm font-semibold"
                : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <UploadCloud className="w-3.5 h-3.5" />
              <span>📥 CSV台账 / ERP JSON / 合同深度吞噬拆球</span>
            </button>

            <button
              type="button"
              onClick={() => {
                setActiveTab("snapshot_timemachine");
                loadSnapshots();
              }}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-medium border transition flex items-center gap-2 ${activeTab === "snapshot_timemachine"
                ? "bg-[#a8c7fa] text-[#062e6f] border-[#a8c7fa] shadow-sm font-semibold"
                : "bg-[#1e1f20] hover:bg-[#282a2c] text-[#9aa0a6] border-[#3c4043]"
                }`}
            >
              <Clock className="w-3.5 h-3.5" />
              <span>⏱️ 集群状态快照与时间机器 (Time-Machine)</span>
            </button>
          </div>

          <div className="text-[11px] font-mono text-[#9aa0a6]">
            当前操作工位: <span className="text-[#e3e3e3]">{account.slot_id}</span>
          </div>
        </div>

        {/* Main Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {activeTab === "document_ingestor" ? (
            <>
              {/* Sample Cards & Ingest Form */}
              <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-[#81c995]" />
                    <span className="font-semibold text-[#e3e3e3]">
                      三份高保真企业原始数据样本一键载入
                      {loadingSamples ? " (同步样本中...)" : ""}
                    </span>
                  </div>
                  <span className="text-[11px] text-[#9aa0a6]">
                    支持 CSV 价格库存台账 · JSON ERP BOM 清单 · Markdown 经销商主合同
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                  {samples.map((s, idx) => {
                    const isSelected = docTitle === s.doc_title;
                    const fmt = (s.doc_format || "AUTO").toUpperCase();
                    return (
                      <button
                        key={s.sample_id ?? idx}
                        type="button"
                        onClick={() => {
                          setDocTitle(s.doc_title);
                          setDocFormat(
                            (["CSV", "JSON", "CONTRACT_MD", "AUTO"].includes(
                              fmt
                            )
                              ? fmt
                              : "AUTO") as "CSV" | "JSON" | "CONTRACT_MD" | "AUTO"
                          );
                          setTargetDepartment(
                            s.target_department || "核心业务部"
                          );
                          if (s.target_slot_id) {
                            setTargetSlotId(s.target_slot_id);
                          }
                          setRawContent(s.raw_content);
                        }}
                        className={`p-3 rounded-lg border text-left transition flex flex-col justify-between gap-2 ${isSelected
                          ? "bg-[#81c995]/15 border-[#81c995] text-[#e3e3e3]"
                          : "bg-[#131314] hover:bg-[#1e1f20] border-[#2d2e30] text-[#9aa0a6]"
                          }`}
                      >
                        <div className="space-y-1">
                          <div className="flex items-center justify-between gap-2">
                            <span
                              className={`font-semibold text-xs line-clamp-1 ${isSelected ? "text-[#81c995]" : "text-[#e3e3e3]"
                                }`}
                            >
                              {s.doc_title}
                            </span>
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-[#282a2c] text-[#a8c7fa] shrink-0">
                              {fmt}
                            </span>
                          </div>
                          {s.description && (
                            <p className="text-[11px] text-[#9aa0a6] line-clamp-2">
                              {s.description}
                            </p>
                          )}
                        </div>
                        <div className="text-[10px] font-mono text-[#9aa0a6] pt-1 border-t border-[#2d2e30]/60">
                          归属部门: {s.target_department}
                        </div>
                      </button>
                    );
                  })}
                </div>

                <form onSubmit={handleIngestDocument} className="space-y-3 pt-1">
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        台账 / 合同名称 (`doc_title`)
                      </label>
                      <input
                        required
                        value={docTitle}
                        onChange={(e) => setDocTitle(e.target.value)}
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        模态格式 (`doc_format`)
                      </label>
                      <select
                        value={docFormat}
                        onChange={(e) =>
                          setDocFormat(
                            e.target.value as
                            | "CSV"
                            | "JSON"
                            | "CONTRACT_MD"
                            | "AUTO"
                          )
                        }
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        <option value="CSV">CSV (阶梯价格/库存结构化台账)</option>
                        <option value="JSON">JSON (ERP BOM表/系统接口配置)</option>
                        <option value="CONTRACT_MD">
                          CONTRACT_MD (经销商返利/法务主合同)
                        </option>
                        <option value="AUTO">AUTO (自动嗅探识别格式)</option>
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        目标业务部门 (`target_department`)
                      </label>
                      <input
                        required
                        value={targetDepartment}
                        onChange={(e) => setTargetDepartment(e.target.value)}
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-[11px] text-[#9aa0a6] block">
                        自动挂载至目标工位 (`target_slot_id`)
                      </label>
                      <select
                        value={targetSlotId}
                        onChange={(e) => setTargetSlotId(e.target.value)}
                        className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                      >
                        {availableSlots.map((s) => (
                          <option key={s.slot_id} value={s.slot_id}>
                            {s.slot_name} ({s.slot_id})
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      原始 CSV 台账 / ERP JSON / 合同全文内容 (`raw_content`)
                    </label>
                    <textarea
                      required
                      rows={6}
                      value={rawContent}
                      onChange={(e) => setRawContent(e.target.value)}
                      placeholder="粘贴企业 CSV 表格、JSON 数据或合同 Markdown 文本..."
                      className="w-full bg-[#0d0e10] border border-[#3c4043] focus:border-[#81c995] rounded-lg px-3 py-2 font-mono text-[11px] text-[#e3e3e3] outline-none leading-relaxed"
                    />
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                    <label className="flex items-center gap-2 text-[11px] text-[#e3e3e3] cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={autoForgeSkill}
                        onChange={(e) => setAutoForgeSkill(e.target.checked)}
                        className="rounded border-[#3c4043] bg-[#131314] text-[#81c995]"
                      />
                      <span>
                        内嵌原始字典并自动编译可执行的 Python 查表/计价技能球 (`SKILL`)，当场在
                        `python -I` 沙箱中实弹验证
                      </span>
                    </label>

                    <button
                      type="submit"
                      disabled={
                        ingesting || !docTitle.trim() || !rawContent.trim()
                      }
                      className="px-5 py-2 rounded-lg bg-[#81c995] hover:bg-[#95d5a7] text-[#0d3b1e] font-semibold text-xs flex items-center gap-2 disabled:opacity-40 transition shadow-md"
                    >
                      {ingesting ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin" />
                          <span>
                            正在解析 Schema 画像、编译四维球体并运行沙箱实测...
                          </span>
                        </>
                      ) : (
                        <>
                          <UploadCloud className="w-4 h-4" />
                          <span>🧬 深度吞噬并编译可执行球体</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </div>

              {/* Ingest Result Display */}
              {ingestResult && (
                <div className="space-y-4">
                  {/* Summary & Sandbox Verification Badge */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#81c995]/50 space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-2.5">
                        <CheckCircle2 className="w-5 h-5 text-[#81c995]" />
                        <div>
                          <div className="font-semibold text-sm text-[#e3e3e3]">
                            {ingestResult.doc_title} · 深度吞噬完成
                          </div>
                          <div className="text-[11px] text-[#9aa0a6]">
                            {ingestResult.summary}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 font-mono text-[11px]">
                        <span className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] text-[#a8c7fa]">
                          Format: {ingestResult.detected_format}
                        </span>
                        <span className="px-2.5 py-1 rounded bg-[#131314] border border-[#2d2e30] text-[#81c995]">
                          Mounted: {ingestResult.mounted_to_slot_id ?? targetSlotId}
                        </span>
                      </div>
                    </div>

                    {/* Schema Profile & Sandbox Verification Grid */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 pt-1">
                      {/* Schema Profile */}
                      <div className="p-3 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-[#a8c7fa] flex items-center gap-1.5">
                            <Table className="w-3.5 h-3.5" />
                            <span>数据表结构与统计画像 (`schema_profile`)</span>
                          </span>
                          <span className="font-mono text-[10px] text-[#9aa0a6]">
                            Ingestion #{ingestResult.ingestion_id}
                          </span>
                        </div>
                        <pre className="p-2.5 rounded bg-[#18191b] border border-[#2d2e30] font-mono text-[10px] text-[#e3e3e3] overflow-x-auto max-h-44 whitespace-pre-wrap">
                          {JSON.stringify(ingestResult.schema_profile, null, 2)}
                        </pre>
                      </div>

                      {/* Sandbox Verification */}
                      <div className="p-3 rounded-lg bg-[#131314] border border-[#81c995]/40 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-[#81c995] flex items-center gap-1.5">
                            <Terminal className="w-3.5 h-3.5" />
                            <span>
                              沙箱实弹验证徽章 (`sandbox_verification` · python -I)
                            </span>
                          </span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/20 text-[#81c995] font-bold">
                            {ingestResult.sandbox_verification?.verified !==
                              false &&
                              ingestResult.sandbox_verification?.executed_ok !==
                              false
                              ? "✓ CLEANROOM_VERIFIED"
                              : "SANDBOX_CHECKED"}
                          </span>
                        </div>
                        <pre className="p-2.5 rounded bg-[#18191b] border border-[#2d2e30] font-mono text-[10px] text-[#81c995] overflow-x-auto max-h-44 whitespace-pre-wrap">
                          {JSON.stringify(
                            ingestResult.sandbox_verification,
                            null,
                            2
                          )}
                        </pre>
                      </div>
                    </div>
                  </div>

                  {/* Newly Minted Capability Balls */}
                  <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Layers className="w-4 h-4 text-[#a8c7fa]" />
                        <span className="font-semibold text-[#e3e3e3]">
                          新诞生的四维原子能力球 (`created_balls`: DATA / SKILL /
                          AUTHORITY / REDLINE)
                        </span>
                      </div>
                      <span className="font-mono text-[11px] text-[#81c995]">
                        共生成 {ingestResult.created_balls?.length ?? 0} 颗球体
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {(ingestResult.created_balls ?? []).map((b, idx) => (
                        <div
                          key={b.ball_id ?? idx}
                          className="p-3.5 rounded-lg bg-[#131314] border border-[#2d2e30] space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${ballTypeBadge(
                                  b.ball_type
                                )}`}
                              >
                                {b.ball_type}
                              </span>
                              <span className="font-semibold text-[#e3e3e3] text-xs">
                                {b.title}
                              </span>
                            </div>
                            <span className="font-mono text-[10px] text-[#9aa0a6]">
                              {b.ball_id}
                            </span>
                          </div>

                          <pre className="p-2.5 rounded bg-[#18191b] border border-[#2d2e30] font-mono text-[10px] text-[#e3e3e3] max-h-36 overflow-y-auto whitespace-pre-wrap">
                            {b.content}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          ) : (
            /* Tab 2: Cluster Snapshot & Time-Machine */
            <div className="space-y-4">
              {/* Save New Snapshot Card */}
              <form
                onSubmit={handleSaveSnapshot}
                className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Save className="w-4 h-4 text-[#a8c7fa]" />
                    <span className="font-semibold text-[#e3e3e3]">
                      创建全量集群磁盘快照 (`POST /api/v1/snapshots/save`)
                    </span>
                  </div>
                  <span className="text-[11px] text-[#9aa0a6]">
                    完整冻结当前部门拓扑、工位容器、账号权限、能力球库与 WORM 审计链状态
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      快照标签名称 (`label`)
                    </label>
                    <input
                      required
                      value={snapshotLabel}
                      onChange={(e) => setSnapshotLabel(e.target.value)}
                      placeholder="例如：大促会战前基线快照 v1"
                      className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-[11px] text-[#9aa0a6] block">
                      快照备注说明 (`note`)
                    </label>
                    <input
                      value={snapshotNote}
                      onChange={(e) => setSnapshotNote(e.target.value)}
                      placeholder="输入保存原因或实验节点说明..."
                      className="w-full bg-[#131314] border border-[#3c4043] focus:border-[#a8c7fa] rounded-lg px-3 py-2 text-xs text-[#e3e3e3] outline-none"
                    />
                  </div>

                  <button
                    type="submit"
                    disabled={savingSnapshot || !snapshotLabel.trim()}
                    className="px-5 py-2 rounded-lg bg-[#a8c7fa] hover:bg-[#b8d2fc] text-[#062e6f] font-semibold text-xs flex items-center justify-center gap-2 disabled:opacity-40 transition shadow-md"
                  >
                    {savingSnapshot ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>正在序列化集群状态并写入磁盘...</span>
                      </>
                    ) : (
                      <>
                        <Save className="w-4 h-4" />
                        <span>💾 立即保存当前全量集群快照</span>
                      </>
                    )}
                  </button>
                </div>
              </form>

              {/* Historical Disk Snapshots List */}
              <div className="p-4 rounded-xl bg-[#18191b] border border-[#2d2e30] space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <History className="w-4 h-4 text-[#81c995]" />
                    <span className="font-semibold text-[#e3e3e3]">
                      历史磁盘快照列表与一键时间回滚 (`GET /api/v1/snapshots/list`)
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={loadSnapshots}
                    className="px-2.5 py-1 rounded bg-[#131314] hover:bg-[#282a2c] border border-[#3c4043] text-[11px] text-[#9aa0a6] hover:text-[#e3e3e3] transition"
                  >
                    {loadingSnapshots ? "刷新中..." : "🔄 刷新快照列表"}
                  </button>
                </div>

                {snapshots.length === 0 ? (
                  <div className="p-8 rounded-lg bg-[#131314] border border-[#2d2e30] text-center space-y-2">
                    <Archive className="w-6 h-6 text-[#9aa0a6] mx-auto" />
                    <div className="text-xs text-[#e3e3e3]">
                      当前暂无已保存的磁盘快照记录
                    </div>
                    <p className="text-[11px] text-[#9aa0a6]">
                      点击上方「💾 立即保存当前全量集群快照」即可创建第一个时间锚点，随时一键回滚恢复
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {snapshots.map((snap) => {
                      const isRestoring = restoringId === snap.snapshot_id;
                      const isDeleting = deletingId === snap.snapshot_id;
                      const st = snap.stats ?? {};
                      const deptsCount =
                        st.departments_count ?? st.departments ?? "—";
                      const slotsCount = st.slots_count ?? st.slots ?? "—";
                      const accountsCount =
                        st.accounts_count ?? st.accounts ?? "—";
                      const ballsCount = st.balls_count ?? st.balls ?? "—";
                      return (
                        <div
                          key={snap.snapshot_id}
                          className="p-4 rounded-xl bg-[#131314] border border-[#2d2e30] hover:border-[#a8c7fa]/50 transition flex flex-col justify-between gap-3"
                        >
                          <div className="space-y-2">
                            <div className="flex items-start justify-between gap-2">
                              <div>
                                <div className="font-semibold text-xs text-[#e3e3e3] flex items-center gap-2 flex-wrap">
                                  <span>{snap.label}</span>
                                </div>
                                <div className="font-mono text-[10px] text-[#9aa0a6] mt-0.5">
                                  ID: {snap.snapshot_id} · 保存于:{" "}
                                  {snap.created_at}
                                </div>
                              </div>
                              <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#81c995]/15 text-[#81c995] border border-[#81c995]/30 shrink-0">
                                {snap.workspace_mode || "DISK_READY"}
                              </span>
                            </div>

                            {(snap.enterprise_name || snap.workspace_mode) && (
                              <div className="flex flex-wrap items-center gap-1.5">
                                {snap.enterprise_name && (
                                  <span className="px-2 py-0.5 rounded text-[10px] bg-[#a8c7fa]/15 text-[#a8c7fa] border border-[#a8c7fa]/30 flex items-center gap-1">
                                    <Building2 className="w-3 h-3 shrink-0" />
                                    <span>{snap.enterprise_name}</span>
                                  </span>
                                )}
                                {snap.workspace_mode && (
                                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-[#fdd663]/10 text-[#fdd663] border border-[#fdd663]/30">
                                    MODE: {snap.workspace_mode}
                                  </span>
                                )}
                              </div>
                            )}

                            {snap.note && (
                              <div className="text-[11px] text-[#9aa0a6]">
                                {snap.note}
                              </div>
                            )}

                            {/* Stats Pills */}
                            <div className="grid grid-cols-4 gap-1.5 pt-1 font-mono text-[10px]">
                              <div className="p-1.5 rounded bg-[#18191b] border border-[#2d2e30] text-center">
                                <div className="text-[#9aa0a6]">部门数</div>
                                <div className="text-[#e3e3e3] font-bold">
                                  {String(deptsCount)}
                                </div>
                              </div>
                              <div className="p-1.5 rounded bg-[#18191b] border border-[#2d2e30] text-center">
                                <div className="text-[#9aa0a6]">工位容器</div>
                                <div className="text-[#a8c7fa] font-bold">
                                  {String(slotsCount)}
                                </div>
                              </div>
                              <div className="p-1.5 rounded bg-[#18191b] border border-[#2d2e30] text-center">
                                <div className="text-[#9aa0a6]">账号体系</div>
                                <div className="text-[#fdd663] font-bold">
                                  {String(accountsCount)}
                                </div>
                              </div>
                              <div className="p-1.5 rounded bg-[#18191b] border border-[#2d2e30] text-center">
                                <div className="text-[#9aa0a6]">能力球数</div>
                                <div className="text-[#81c995] font-bold">
                                  {String(ballsCount)}
                                </div>
                              </div>
                            </div>

                            {snap.head_hash && (
                              <div className="flex items-center gap-1.5 font-mono text-[10px] text-[#9aa0a6] pt-1">
                                <ShieldCheck className="w-3.5 h-3.5 text-[#81c995] shrink-0" />
                                <span className="truncate">
                                  WORM Blackbox Hash: {snap.head_hash}
                                </span>
                              </div>
                            )}
                          </div>

                          <div className="pt-2 border-t border-[#2d2e30] flex items-center justify-between gap-2">
                            <button
                              type="button"
                              disabled={Boolean(restoringId || deletingId)}
                              onClick={() => handleDeleteSnapshot(snap)}
                              className="px-2.5 py-1.5 rounded-lg bg-[#1e1f20] hover:bg-[#f28b82]/20 text-[#9aa0a6] hover:text-[#f28b82] border border-[#3c4043] hover:border-[#f28b82]/50 font-medium text-xs flex items-center gap-1 transition disabled:opacity-40"
                              title="删除此磁盘快照"
                            >
                              {isDeleting ? (
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="w-3.5 h-3.5" />
                              )}
                              <span>删除</span>
                            </button>

                            <button
                              type="button"
                              disabled={Boolean(restoringId || deletingId)}
                              onClick={() => handleRestoreSnapshot(snap)}
                              className="px-3.5 py-1.5 rounded-lg bg-[#282a2c] hover:bg-[#a8c7fa] text-[#e3e3e3] hover:text-[#062e6f] border border-[#3c4043] hover:border-[#a8c7fa] font-medium text-xs flex items-center gap-1.5 transition disabled:opacity-40"
                            >
                              {isRestoring ? (
                                <>
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  <span>正在切换/恢复全站集群...</span>
                                </>
                              ) : (
                                <>
                                  <RotateCcw className="w-3.5 h-3.5" />
                                  <span>⏪ 切换/恢复到此企业快照</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
