import { useState } from "react";
import { publishEvolutionCandidate } from "../api";
import { ArenaReport } from "../types";

export type CandidateReviewReport = Pick<ArenaReport, "proposal_id" | "promoted" | "source_hash" | "candidate_status" | "validation_status"> & { proposer_id?: string };

export function CandidateReview({ report, reviewerId, onPublished }: {
  report: CandidateReviewReport; reviewerId?: string; onPublished?: (report?: CandidateReviewReport) => Promise<void>;
}) {
  const [samplesJson, setSamplesJson] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (report.promoted || report.candidate_status === "ACTIVE") return null;
  if (report.proposer_id && report.proposer_id === reviewerId) return <p className="text-xs text-[#fdd663]">当前账号为候选创建人，请由另一名有权限的管理账号独立审核并发布。</p>;
  if (report.candidate_status === "REJECTED") return <p className="text-xs text-[#f28b82]">候选已拒绝 · {report.validation_status ?? "未通过验证"}</p>;
  return <form className="space-y-2 text-xs" onSubmit={async event => {
    event.preventDefault();
    if (!reviewerId || !report.source_hash || !confirmed || busy) return;
    setMessage(null);
    try {
      const samples: unknown = JSON.parse(samplesJson);
      if (!Array.isArray(samples) || samples.length < 3 || samples.some(sample =>
        !sample || typeof sample.input_payload !== "object" || Array.isArray(sample.input_payload) ||
        sample.input_payload === null || !("expected_output" in sample))) {
        throw new Error("请提供至少 3 个独立测试用例，每项包含 input_payload 对象和 expected_output。");
      }
      setBusy(true);
      const result = await publishEvolutionCandidate(report.proposal_id, {
        reviewer_id: reviewerId, approved_source_hash: report.source_hash, independent_samples: samples,
      });
      setMessage(result.report?.promoted === true ? "独立验证通过，已发布。" : `尚未发布：${result.status ?? "请查看验证结果"}`);
      await onPublished?.(result.report);
    } catch (error) { setMessage(error instanceof Error ? error.message : "发布失败，请重试。"); }
    finally { setBusy(false); }
  }}>
    <p className="text-[#fdd663]">候选技能尚未挂载。验证状态：{report.validation_status ?? "待独立验证"}</p>
    <p className="font-mono text-[10px] break-all">源代码 SHA-256：{report.source_hash ?? "未提供，无法发布"}</p>
    <label className="block text-[#9aa0a6]">独立用例 JSON 数组（至少 3 项，包含未见输入；由后端验证证据独立性）
      <textarea required value={samplesJson} onChange={event => setSamplesJson(event.target.value)} placeholder={'[{"input_payload":{},"expected_output":{}}]'} className="block w-full mt-1 p-2 rounded bg-[#131314] border border-[#3c4043] font-mono" />
    </label>
    <label className="flex gap-2 items-center"><input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已审阅上方完整代码，并确认此源代码哈希与独立用例。</label>
    <button disabled={!reviewerId || !report.source_hash || !confirmed || busy} className="px-3 py-1 rounded border border-[#3c4043] disabled:opacity-40">{busy ? "正在验证…" : "验证并发布候选技能"}</button>
    {message && <p role="status" className="text-[#fdd663] whitespace-pre-wrap">{message}</p>}
  </form>;
}
