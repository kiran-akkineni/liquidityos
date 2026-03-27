import { useEffect, useState } from 'react';
import { api, cents } from '../api';
import Card from '../components/Card';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getDashboard().then(setStats).catch(e => setErr(e.message));
  }, []);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!stats) return <div className="text-gray-500">Loading...</div>;

  return (
    <div>
      <h1 className="text-2xl font-semibold text-white mb-6">Dashboard</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card label="Total GMV" value={cents(stats.total_gmv_cents)} />
        <Card label="Platform Revenue" value={cents(stats.total_revenue_cents)} />
        <Card label="Active Lots" value={stats.lots_active} sub={`${stats.lots_sold} sold`} />
        <Card label="Active Sellers" value={stats.sellers_active} sub={`${stats.sellers_total} total`} />
        <Card label="Active Buyers" value={stats.buyers_active} sub={`${stats.buyers_total} total`} />
        <Card label="Orders" value={stats.orders_total} sub={`${stats.orders_completed} completed`} />
        <Card label="Open Disputes" value={stats.disputes_open} />
        <Card label="Pending Offers" value={stats.offers_pending} />
      </div>
    </div>
  );
}
