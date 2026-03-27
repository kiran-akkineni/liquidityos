import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, cents, shortDate } from '../api';
import StatusBadge from '../components/StatusBadge';

export default function DisputeDetail() {
  const { disputeId } = useParams();
  const [dispute, setDispute] = useState(null);
  const [err, setErr] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [form, setForm] = useState({
    resolution_type: 'PARTIAL_REFUND',
    refund_amount_cents: 0,
    reasoning: '',
  });
  const [resolveErr, setResolveErr] = useState(null);

  const load = () => api.getDispute(disputeId).then(setDispute).catch(e => setErr(e.message));
  useEffect(() => { load(); }, [disputeId]);

  async function handleResolve(e) {
    e.preventDefault();
    setResolveErr(null);
    try {
      await api.resolveDispute(disputeId, {
        resolution_type: form.resolution_type,
        refund_amount_cents: parseInt(form.refund_amount_cents) || 0,
        reasoning: form.reasoning,
      });
      setResolving(false);
      load();
    } catch (err) {
      setResolveErr(err.message);
    }
  }

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!dispute) return <div className="text-gray-500">Loading...</div>;

  const evidence = dispute.buyer_evidence || [];
  const sellerResp = dispute.seller_response || {};

  return (
    <div>
      <Link to="/disputes" className="text-sm text-gray-500 hover:text-gray-300 mb-4 inline-block">&larr; Back to Disputes</Link>
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-2xl font-semibold text-white">Dispute {dispute.dispute_id}</h1>
        <StatusBadge status={dispute.status} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Details */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Details</h3>
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span className="text-gray-500">Order</span><Link to={`/orders/${dispute.order_id}`} className="text-blue-400 hover:underline font-mono text-xs">{dispute.order_id}</Link></div>
            <div className="flex justify-between"><span className="text-gray-500">Type</span><span className="text-gray-200">{dispute.type}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Claimed Amount</span><span className="text-gray-200">{cents(dispute.claimed_amount_cents)}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Affected Units</span><span className="text-gray-200">{dispute.affected_units} / {dispute.total_units}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Buyer</span><span className="text-gray-400 font-mono text-xs">{dispute.buyer_id}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Seller</span><span className="text-gray-400 font-mono text-xs">{dispute.seller_id}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Opened</span><span className="text-gray-200">{shortDate(dispute.opened_at)}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Seller Deadline</span><span className="text-gray-200">{shortDate(dispute.seller_response_deadline)}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Resolution Deadline</span><span className="text-gray-200">{shortDate(dispute.resolution_deadline)}</span></div>
          </div>
          <div className="mt-3 p-3 bg-gray-800/50 rounded">
            <div className="text-xs text-gray-500 mb-1">Description</div>
            <div className="text-sm text-gray-300">{dispute.description}</div>
          </div>
        </div>

        {/* Evidence */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Evidence ({evidence.length})</h3>
          {evidence.length > 0 ? (
            <div className="space-y-2">
              {evidence.map((ev, i) => (
                <div key={i} className="p-3 bg-gray-800/50 rounded text-sm">
                  <div className="flex justify-between text-xs text-gray-500 mb-1">
                    <span>{ev.submitted_by || 'buyer'}</span>
                    <span>{ev.type}</span>
                  </div>
                  <div className="text-gray-300">{ev.description || ev.url}</div>
                  {ev.url && <div className="text-xs text-gray-500 mt-1 truncate">{ev.url}</div>}
                </div>
              ))}
            </div>
          ) : <p className="text-sm text-gray-500">No evidence submitted</p>}
        </div>

        {/* Seller Response */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Seller Response</h3>
          {sellerResp.message ? (
            <div className="space-y-2 text-sm">
              <div className="p-3 bg-gray-800/50 rounded">
                <div className="text-gray-300">{sellerResp.message}</div>
              </div>
              {sellerResp.proposed_resolution && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">Proposed</span>
                  <span className="text-gray-200">{sellerResp.proposed_resolution} ({cents(sellerResp.proposed_refund_cents)})</span>
                </div>
              )}
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Responded At</span>
                <span className="text-gray-200">{shortDate(sellerResp.responded_at)}</span>
              </div>
            </div>
          ) : <p className="text-sm text-gray-500">No response yet</p>}
        </div>

        {/* Resolve */}
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Resolution</h3>
          {dispute.status === 'RESOLVED' ? (
            <div className="space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-gray-500">Resolution ID</span><span className="text-gray-200 font-mono text-xs">{dispute.resolution_id}</span></div>
              <div className="flex justify-between"><span className="text-gray-500">Resolved</span><span className="text-gray-200">{shortDate(dispute.resolved_at)}</span></div>
            </div>
          ) : resolving ? (
            <form onSubmit={handleResolve} className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Resolution Type</label>
                <select value={form.resolution_type} onChange={e => setForm({...form, resolution_type: e.target.value})}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200">
                  <option value="FULL_REFUND">Full Refund</option>
                  <option value="PARTIAL_REFUND">Partial Refund</option>
                  <option value="NO_REFUND">No Refund</option>
                  <option value="REPLACEMENT">Replacement</option>
                  <option value="CREDIT">Credit</option>
                </select>
              </div>
              {(form.resolution_type === 'PARTIAL_REFUND') && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Refund Amount (cents)</label>
                  <input type="number" value={form.refund_amount_cents}
                    onChange={e => setForm({...form, refund_amount_cents: e.target.value})}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" />
                </div>
              )}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Reasoning</label>
                <textarea value={form.reasoning} onChange={e => setForm({...form, reasoning: e.target.value})}
                  rows={3} className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200" />
              </div>
              {resolveErr && <div className="text-red-400 text-sm">{resolveErr}</div>}
              <div className="flex gap-2">
                <button type="submit" className="px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white text-sm rounded">
                  Submit Resolution
                </button>
                <button type="button" onClick={() => setResolving(false)}
                  className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded">
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button onClick={() => setResolving(true)}
              disabled={dispute.status === 'RESOLVED' || dispute.status === 'CLOSED'}
              className="px-4 py-2 bg-blue-700 hover:bg-blue-600 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded">
              Resolve Dispute
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
