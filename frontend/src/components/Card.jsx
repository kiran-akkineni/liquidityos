export default function Card({ label, value, sub }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-2xl font-semibold text-white">{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}
