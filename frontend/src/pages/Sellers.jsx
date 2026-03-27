import { useEffect, useState } from 'react';
import { api, cents } from '../api';
import StatusBadge from '../components/StatusBadge';

export default function Sellers() {
  const [sellers, setSellers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState(null);

  const load = () => api.getSellers().then(d => setSellers(d.sellers)).catch(e => setErr(e.message));
  useEffect(() => { load(); }, []);

  async function verify(id, decision) {
    await api.verifySeller(id, decision);
    load();
    setSelected(null);
  }

  if (err) return <div className="text-red-400">Error: {err}</div>;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Sellers</h1>

      {selected && (
        <div className="mb-6 bg-gray-900 border border-gray-800 rounded-lg p-5">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h2 className="text-lg font-semibold text-white">{selected.business_name}</h2>
              <p className="text-sm text-gray-400">{selected.seller_id}</p>
            </div>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-gray-300 text-sm">Close</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span className="text-gray-500">Type:</span> <span className="text-gray-200">{selected.seller_type}</span></div>
            <div><span className="text-gray-500">Status:</span> <StatusBadge status={selected.status} /></div>
            <div><span className="text-gray-500">Quality Score:</span> <span className="text-gray-200">{selected.quality_score}</span></div>
            <div><span className="text-gray-500">Transactions:</span> <span className="text-gray-200">{selected.total_transactions}</span></div>
            <div><span className="text-gray-500">GMV:</span> <span className="text-gray-200">{cents(selected.total_gmv_cents)}</span></div>
            <div><span className="text-gray-500">Dispute Rate:</span> <span className="text-gray-200">{selected.dispute_rate_pct}%</span></div>
            <div><span className="text-gray-500">Contact:</span> <span className="text-gray-200">{selected.primary_contact_name}</span></div>
            <div><span className="text-gray-500">Email:</span> <span className="text-gray-200">{selected.primary_contact_email}</span></div>
          </div>
          {selected.status === 'PENDING_VERIFICATION' && (
            <div className="mt-4 flex gap-2">
              <button onClick={() => verify(selected.seller_id, 'APPROVED')}
                className="px-4 py-2 bg-green-700 hover:bg-green-600 text-white text-sm rounded">
                Approve
              </button>
              <button onClick={() => verify(selected.seller_id, 'REJECTED')}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 text-white text-sm rounded">
                Reject
              </button>
            </div>
          )}
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-gray-500 uppercase bg-gray-900/50 border-b border-gray-800">
            <tr>
              <th className="px-4 py-3">Business Name</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Quality</th>
              <th className="px-4 py-3 text-right">Transactions</th>
              <th className="px-4 py-3 text-right">GMV</th>
              <th className="px-4 py-3 text-right">Dispute %</th>
            </tr>
          </thead>
          <tbody>
            {sellers.map(s => (
              <tr key={s.seller_id} onClick={() => setSelected(s)}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer">
                <td className="px-4 py-3 text-gray-200 font-medium">{s.business_name}</td>
                <td className="px-4 py-3 text-gray-400">{s.seller_type}</td>
                <td className="px-4 py-3"><StatusBadge status={s.status} /></td>
                <td className="px-4 py-3 text-right text-gray-300">{s.quality_score}</td>
                <td className="px-4 py-3 text-right text-gray-300">{s.total_transactions}</td>
                <td className="px-4 py-3 text-right text-gray-300">{cents(s.total_gmv_cents)}</td>
                <td className="px-4 py-3 text-right text-gray-300">{s.dispute_rate_pct}%</td>
              </tr>
            ))}
            {sellers.length === 0 && (
              <tr><td colSpan="7" className="px-4 py-8 text-center text-gray-500">No sellers found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
