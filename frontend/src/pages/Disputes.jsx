import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, cents, shortDate } from '../api';
import StatusBadge from '../components/StatusBadge';

export default function Disputes() {
  const [disputes, setDisputes] = useState([]);
  const [err, setErr] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.getDisputes().then(d => setDisputes(d.disputes)).catch(e => setErr(e.message));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Disputes</h1>
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-gray-500 uppercase bg-gray-900/50 border-b border-gray-800">
            <tr>
              <th className="px-4 py-3">Dispute ID</th>
              <th className="px-4 py-3">Order</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Claimed</th>
              <th className="px-4 py-3">Seller Deadline</th>
              <th className="px-4 py-3">Opened</th>
            </tr>
          </thead>
          <tbody>
            {disputes.map(d => (
              <tr key={d.dispute_id} onClick={() => nav(`/disputes/${d.dispute_id}`)}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer">
                <td className="px-4 py-3 text-gray-200 font-mono text-xs">{d.dispute_id}</td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{d.order_id?.slice(0, 16)}</td>
                <td className="px-4 py-3 text-gray-300">{d.type}</td>
                <td className="px-4 py-3"><StatusBadge status={d.status} /></td>
                <td className="px-4 py-3 text-right text-gray-200">{cents(d.claimed_amount_cents)}</td>
                <td className="px-4 py-3 text-gray-400">{shortDate(d.seller_response_deadline)}</td>
                <td className="px-4 py-3 text-gray-400">{shortDate(d.opened_at)}</td>
              </tr>
            ))}
            {disputes.length === 0 && (
              <tr><td colSpan="7" className="px-4 py-8 text-center text-gray-500">No disputes found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
