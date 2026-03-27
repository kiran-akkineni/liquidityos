import { useEffect, useState } from 'react';
import { api, cents, shortDate } from '../api';
import StatusBadge from '../components/StatusBadge';

export default function Lots() {
  const [lots, setLots] = useState([]);
  const [selected, setSelected] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getLots().then(d => setLots(d.lots)).catch(e => setErr(e.message));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Lots</h1>

      {selected && (
        <div className="mb-6 bg-gray-900 border border-gray-800 rounded-lg p-5">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h2 className="text-lg font-semibold text-white">{selected.title}</h2>
              <p className="text-sm text-gray-400">{selected.lot_id} &middot; Seller: {selected.seller_id}</p>
            </div>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-gray-300 text-sm">Close</button>
          </div>
          <p className="text-sm text-gray-400 mb-4">{selected.description}</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div><span className="text-gray-500">Status:</span> <StatusBadge status={selected.status} /></div>
            <div><span className="text-gray-500">Ask Price:</span> <span className="text-gray-200">{cents(selected.ask_price_cents)}</span></div>
            <div><span className="text-gray-500">Floor Price:</span> <span className="text-gray-200">{cents(selected.floor_price_cents)}</span></div>
            <div><span className="text-gray-500">Pricing Mode:</span> <span className="text-gray-200">{selected.pricing_mode}</span></div>
            <div><span className="text-gray-500">Units:</span> <span className="text-gray-200">{selected.total_units}</span></div>
            <div><span className="text-gray-500">SKUs:</span> <span className="text-gray-200">{selected.total_skus}</span></div>
            <div><span className="text-gray-500">Pallets:</span> <span className="text-gray-200">{selected.pallet_count}</span></div>
            <div><span className="text-gray-500">Weight:</span> <span className="text-gray-200">{selected.total_weight_lb} lb</span></div>
            <div><span className="text-gray-500">Category:</span> <span className="text-gray-200">{selected.category_primary}</span></div>
            <div><span className="text-gray-500">Condition:</span> <span className="text-gray-200">{selected.condition_primary}</span></div>
            <div><span className="text-gray-500">Retail Value:</span> <span className="text-gray-200">{cents(selected.estimated_retail_value_cents)}</span></div>
            <div><span className="text-gray-500">Ship From:</span> <span className="text-gray-200">{selected.ship_from_city}, {selected.ship_from_state} {selected.ship_from_zip}</span></div>
            <div><span className="text-gray-500">Views:</span> <span className="text-gray-200">{selected.views}</span></div>
            <div><span className="text-gray-500">Offers:</span> <span className="text-gray-200">{selected.offers_received}</span></div>
            <div><span className="text-gray-500">Top Brands:</span> <span className="text-gray-200">{(selected.top_brands || []).join(', ')}</span></div>
            <div><span className="text-gray-500">Expires:</span> <span className="text-gray-200">{shortDate(selected.expires_at)}</span></div>
          </div>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-gray-500 uppercase bg-gray-900/50 border-b border-gray-800">
            <tr>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Ask Price</th>
              <th className="px-4 py-3 text-right">Units</th>
              <th className="px-4 py-3">Condition</th>
              <th className="px-4 py-3">Category</th>
              <th className="px-4 py-3 text-right">Offers</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {lots.map(l => (
              <tr key={l.lot_id} onClick={() => setSelected(l)}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer">
                <td className="px-4 py-3 text-gray-200 font-medium max-w-xs truncate">{l.title}</td>
                <td className="px-4 py-3"><StatusBadge status={l.status} /></td>
                <td className="px-4 py-3 text-right text-gray-300">{cents(l.ask_price_cents)}</td>
                <td className="px-4 py-3 text-right text-gray-300">{l.total_units}</td>
                <td className="px-4 py-3 text-gray-400">{l.condition_primary}</td>
                <td className="px-4 py-3 text-gray-400">{l.category_primary}</td>
                <td className="px-4 py-3 text-right text-gray-300">{l.offers_received}</td>
                <td className="px-4 py-3 text-gray-400">{shortDate(l.created_at)}</td>
              </tr>
            ))}
            {lots.length === 0 && (
              <tr><td colSpan="8" className="px-4 py-8 text-center text-gray-500">No lots found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
