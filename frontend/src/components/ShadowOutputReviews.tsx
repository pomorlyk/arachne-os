import { useState } from "react";
import { submitShadowOutputReview } from "../api";
import { ReviewableOutput, RoleViewType } from "../types";

export function ShadowOutputReviews({ outputs, reviewerId, roleView, onReviewed }: {
  outputs: ReviewableOutput[];
  reviewerId?: string;
  roleView: RoleViewType;
  onReviewed?: () => Promise<void>;
}) {
  const [selectedTicket, setSelectedTicket] = useState<string | null>(null);
  const [finalText, setFinalText] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewedIds, setReviewedIds] = useState<Set<string>>(() => new Set());
  if ((roleView !== "manager" && roleView !== "boss") || !reviewerId) return null;
  const available = outputs.filter(output => output.initiator_id !== reviewerId);
  const selected = available.find(output => output.ticket_id === selectedTicket && !output.reviewed && !reviewedIds.has(output.ticket_id));
  return <section className="p-3 rounded-lg bg-[#1e1f20] border border-[#3c4043] space-y-2 text-xs" aria-label="已完成工单独立复核">
    <h4 className="font-medium text-[#e3e3e3]">已完成工单 · 独立交付复核</h4>
    <p className="text-[11px] text-[#9aa0a6]">依据实际 AI 草稿与人工最终交付文本形成评分证据。每个工单仅接受一次复核，不能复核自己发起的工单。</p>
    {available.length === 0 && <p className="text-[#9aa0a6]">暂无可独立复核的已完成工单。</p>}
    <div className="space-y-1 max-h-36 overflow-y-auto">
      {available.map(output => <div key={output.ticket_id} className="flex flex-wrap items-center justify-between gap-2 p-2 rounded bg-[#131314]">
        <span className="font-mono break-all">{output.ticket_id}</span>
        <span className="text-[#9aa0a6]">发起人：{output.initiator_id}</span>
        {output.reviewed || reviewedIds.has(output.ticket_id) ? <span className="text-[#81c995]">已复核</span> : <button disabled={busy} className="px-2 py-1 rounded border border-[#3c4043] disabled:opacity-40" onClick={() => {
          setSelectedTicket(output.ticket_id); setFinalText(""); setConfirmed(false); setMessage(null);
        }}>复核最终交付</button>}
      </div>)}
    </div>
    {selected && <form className="space-y-2 pt-2 border-t border-[#3c4043]" onSubmit={async event => {
      event.preventDefault();
      if (!confirmed || !finalText.trim() || busy) return;
      setBusy(true);
      setMessage(null);
      try {
        const result = await submitShadowOutputReview({ticket_id: selected.ticket_id, human_final_text: finalText});
        setReviewedIds(previous => new Set([...previous, selected.ticket_id]));
        setSelectedTicket(null);
        const similarity = result.score?.similarity_ratio;
        const score = result.score?.replaceability_score;
        setMessage(`复核已记录：${result.ticket_id}。相似度 ${typeof similarity === "number" ? `${(similarity * 100).toFixed(1)}%` : "未提供"}；岗位评分 ${typeof score === "number" ? score : "未提供"}。`);
        await onReviewed?.();
      } catch (error) { setMessage(error instanceof Error ? error.message : "复核提交失败，请重试。"); }
      finally { setBusy(false); }
    }}>
      <div className="text-[#9aa0a6]">实际 AI 草稿 · {selected.ticket_id}</div>
      <pre className="p-2 rounded bg-[#131314] whitespace-pre-wrap break-words max-h-48 overflow-y-auto">{selected.ai_draft_text}</pre>
      <button type="button" disabled={busy} onClick={() => { setFinalText(selected.ai_draft_text); setConfirmed(false); }} className="text-[#a8c7fa] underline">将实际草稿载入编辑框</button>
      <label className="block text-[#9aa0a6]">人工最终交付文本
        <textarea required disabled={busy} value={finalText} onChange={event => { setFinalText(event.target.value); setConfirmed(false); }} className="block w-full mt-1 p-2 rounded bg-[#131314] border border-[#3c4043] min-h-24" />
      </label>
      <label className="flex gap-2 items-start"><input type="checkbox" disabled={busy} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />我已核对实际交付文本，并确认提交此独立复核记录。</label>
      <div className="flex gap-2"><button disabled={busy || !confirmed || !finalText.trim()} className="px-3 py-1 rounded border border-[#3c4043] disabled:opacity-40">{busy ? "提交中…" : "确认提交复核"}</button><button type="button" disabled={busy} onClick={() => setSelectedTicket(null)} className="px-3 py-1">取消</button></div>
    </form>}
    {message && <p role="status" className="text-[#fdd663] whitespace-pre-wrap">{message}</p>}
  </section>;
}
