import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api, cents, shortDate } from '../api';
import StatusBadge from '../components/StatusBadge';

function Section({ title, children }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex justify-between py-1 text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200">{value ?? '-'}</span>
    </div>
  );
}

export default function OrderDetail() {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);
  const [escrow, setEscrow] = useState(null);
  const [shipment, setShipment] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [payout, setPayout] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getOrder(orderId).then(setOrder).catch(e => setErr(e.message));
    api.getOrderEscrow(orderId).then(setEscrow);
    api.getOrderShipment(orderId).then(setShipment);
    api.getOrderInvoices(orderId).then(d => setInvoices(d?.invoices || []));
    api.getOrderPayout(orderId).then(setPayout);
  }, [orderId]);

  if (err) return <div className="text-red-400">Error: {err}</div>;
  if (!order) return <div className="text-gray-500">Loading...</div>;

  return (
    <div>
      <Link to="/orders" className="text-sm text-gray-500 hover:text-gray-300 mb-4 inline-block">&larr; Back to Orders</Link>
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-2xl font-semibold text-white">Order {order.order_id}</h1>
        <StatusBadge status={order.status} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Order Details">
          <Row label="Lot" value={order.lot_id} />
          <Row label="Buyer" value={order.buyer_id} />
          <Row label="Seller" value={order.seller_id} />
          <Row label="Lot Price" value={cents(order.lot_price_cents)} />
          <Row label="Platform Fee" value={`${cents(order.platform_fee_cents)} (${order.platform_fee_rate_pct}%)`} />
          <Row label="Freight" value={cents(order.freight_cost_cents)} />
          <Row label="Insurance" value={cents(order.insurance_cents)} />
          <div className="border-t border-gray-800 mt-2 pt-2">
            <Row label="Total Buyer Cost" value={<span className="font-semibold text-white">{cents(order.total_buyer_cost_cents)}</span>} />
            <Row label="Seller Payout" value={cents(order.seller_payout_cents)} />
            <Row label="Platform Revenue" value={<span className="text-green-400">{cents(order.platform_revenue_cents)}</span>} />
          </div>
          <div className="border-t border-gray-800 mt-2 pt-2">
            <Row label="Created" value={shortDate(order.created_at)} />
            <Row label="Completed" value={shortDate(order.completed_at)} />
          </div>
        </Section>

        <Section title="Escrow">
          {escrow ? (
            <>
              <Row label="Escrow ID" value={escrow.escrow_id} />
              <Row label="Status" value={<StatusBadge status={escrow.status} />} />
              <Row label="Total" value={cents(escrow.total_cents)} />
              <Row label="Funding Method" value={escrow.funding_method || '-'} />
              <Row label="Funded At" value={shortDate(escrow.funded_at)} />
              <Row label="Deadline" value={shortDate(escrow.funding_deadline)} />
            </>
          ) : <p className="text-sm text-gray-500">No escrow found</p>}
        </Section>

        <Section title="Shipment">
          {shipment ? (
            <>
              <Row label="Shipment ID" value={shipment.shipment_id} />
              <Row label="Status" value={<StatusBadge status={shipment.status} />} />
              <Row label="Carrier" value={shipment.carrier_name} />
              <Row label="Tracking" value={shipment.tracking_number} />
              <Row label="Cost" value={cents(shipment.cost_cents)} />
              <Row label="Origin" value={`${shipment.origin_city || ''}, ${shipment.origin_state || ''} ${shipment.origin_zip}`} />
              <Row label="Destination" value={`${shipment.destination_city || ''} ${shipment.destination_zip}`} />
              <Row label="Pickup" value={shortDate(shipment.pickup_confirmed_at)} />
              <Row label="Delivered" value={shortDate(shipment.delivery_delivered_at)} />
            </>
          ) : <p className="text-sm text-gray-500">No shipment yet</p>}
        </Section>

        <Section title="Inspection">
          <Row label="Window Opens" value={shortDate(order.inspection_window_opens_at)} />
          <Row label="Window Closes" value={shortDate(order.inspection_window_closes_at)} />
          <Row label="Result" value={order.inspection_result ? <StatusBadge status={order.inspection_result} /> : '-'} />
          <Row label="Method" value={order.inspection_result_method || '-'} />
        </Section>

        <Section title="Payout">
          {payout ? (
            <>
              <Row label="Payout ID" value={payout.payout_id} />
              <Row label="Status" value={<StatusBadge status={payout.status} />} />
              <Row label="Amount" value={cents(payout.amount_cents)} />
              <Row label="Method" value={payout.method} />
              <Row label="Expected Arrival" value={payout.expected_arrival_date} />
            </>
          ) : <p className="text-sm text-gray-500">No payout yet</p>}
        </Section>

        <Section title="Invoices">
          {invoices.length > 0 ? invoices.map(inv => (
            <div key={inv.invoice_id} className="mb-3 last:mb-0 p-3 bg-gray-800/50 rounded">
              <Row label="Invoice" value={inv.invoice_id} />
              <Row label="Type" value={inv.invoice_type} />
              <Row label="Total" value={cents(inv.total_cents)} />
            </div>
          )) : <p className="text-sm text-gray-500">No invoices</p>}
        </Section>
      </div>
    </div>
  );
}
