import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, cents, shortDate } from '../api';
import StatusBadge from '../components/StatusBadge';

export default function Orders() {
  const [orders, setOrders] = useState([]);
  const [err, setErr] = useState(null);
  const nav = useNavigate();

  useEffect(() => {
    api.getOrders().then(d => setOrders(d.orders)).catch(e => setErr(e.message));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Orders</h1>
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-gray-500 uppercase bg-gray-900/50 border-b border-gray-800">
            <tr>
              <th className="px-4 py-3">Order ID</th>
              <th className="px-4 py-3">Buyer</th>
              <th className="px-4 py-3">Seller</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Lot Price</th>
              <th className="px-4 py-3 text-right">Total</th>
              <th className="px-4 py-3 text-right">Revenue</th>
              <th className="px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {orders.map(o => (
              <tr key={o.order_id} onClick={() => nav(`/orders/${o.order_id}`)}
                className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer">
                <td className="px-4 py-3 text-gray-200 font-mono text-xs">{o.order_id}</td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{o.buyer_id?.slice(0, 16)}</td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{o.seller_id?.slice(0, 16)}</td>
                <td className="px-4 py-3"><StatusBadge status={o.status} /></td>
                <td className="px-4 py-3 text-right text-gray-300">{cents(o.lot_price_cents)}</td>
                <td className="px-4 py-3 text-right text-gray-200 font-medium">{cents(o.total_buyer_cost_cents)}</td>
                <td className="px-4 py-3 text-right text-green-400">{cents(o.platform_revenue_cents)}</td>
                <td className="px-4 py-3 text-gray-400">{shortDate(o.created_at)}</td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr><td colSpan="8" className="px-4 py-8 text-center text-gray-500">No orders found</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
