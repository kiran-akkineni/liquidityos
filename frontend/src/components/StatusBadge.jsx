const colors = {
  ACTIVE: 'bg-green-900/50 text-green-400 border-green-800',
  COMPLETED: 'bg-green-900/50 text-green-400 border-green-800',
  SOLD: 'bg-green-900/50 text-green-400 border-green-800',
  RELEASED: 'bg-green-900/50 text-green-400 border-green-800',
  FUNDED: 'bg-blue-900/50 text-blue-400 border-blue-800',
  DELIVERED: 'bg-blue-900/50 text-blue-400 border-blue-800',
  PENDING: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  PENDING_VERIFICATION: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  PENDING_FUNDING: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  AWAITING_PAYMENT: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  AWAITING_SHIPMENT: 'bg-yellow-900/50 text-yellow-400 border-yellow-800',
  DRAFT: 'bg-gray-800 text-gray-400 border-gray-700',
  BOOKED: 'bg-indigo-900/50 text-indigo-400 border-indigo-800',
  SHIPPED: 'bg-indigo-900/50 text-indigo-400 border-indigo-800',
  IN_TRANSIT: 'bg-indigo-900/50 text-indigo-400 border-indigo-800',
  INSPECTION: 'bg-purple-900/50 text-purple-400 border-purple-800',
  OPENED: 'bg-red-900/50 text-red-400 border-red-800',
  DISPUTED: 'bg-red-900/50 text-red-400 border-red-800',
  CANCELLED: 'bg-red-900/50 text-red-400 border-red-800',
  VOIDED: 'bg-red-900/50 text-red-400 border-red-800',
  SELLER_RESPONDED: 'bg-orange-900/50 text-orange-400 border-orange-800',
  RESOLVED: 'bg-gray-800 text-gray-300 border-gray-700',
  INITIATED: 'bg-cyan-900/50 text-cyan-400 border-cyan-800',
  HELD: 'bg-orange-900/50 text-orange-400 border-orange-800',
  PARTIALLY_RELEASED: 'bg-orange-900/50 text-orange-400 border-orange-800',
};

export default function StatusBadge({ status }) {
  const cls = colors[status] || 'bg-gray-800 text-gray-400 border-gray-700';
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${cls}`}>
      {status}
    </span>
  );
}
