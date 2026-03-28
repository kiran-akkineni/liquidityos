// In production (served by Flask), API is same-origin at /v1
// In local dev (Vite), proxy handles /v1 → localhost:8000
const API_BASE = (import.meta.env.VITE_API_URL || '') + '/v1';

let opsToken = null;

async function getOpsToken() {
  if (opsToken) return opsToken;
  const res = await fetch(`${API_BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: 'ops_admin', role: 'ops' }),
  });
  const data = await res.json();
  opsToken = data.token;
  return opsToken;
}

async function apiFetch(path, options = {}) {
  const token = await getOpsToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.error?.message || err?.error?.code || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  getDashboard: () => apiFetch('/admin/dashboard'),
  getSellers: () => apiFetch('/admin/sellers'),
  getBuyers: () => apiFetch('/admin/buyers'),
  getLots: () => apiFetch('/admin/lots'),
  getLot: (id) => apiFetch(`/lots/${id}`),
  getOrders: () => apiFetch('/admin/orders'),
  getOrder: (id) => apiFetch(`/orders/${id}`),
  getOrderEscrow: (id) => apiFetch(`/orders/${id}/escrow`).catch(() => null),
  getOrderShipment: (id) => apiFetch(`/orders/${id}/shipment`).catch(() => null),
  getOrderInvoices: (id) => apiFetch(`/orders/${id}/invoices`).catch(() => ({ invoices: [] })),
  getOrderPayout: (id) => apiFetch(`/orders/${id}/payout`).catch(() => null),
  getDisputes: () => apiFetch('/admin/disputes'),
  getDispute: (id) => apiFetch(`/disputes/${id}`),
  verifySeller: (id, decision) =>
    apiFetch(`/admin/sellers/${id}/verify`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  verifyBuyer: (id, decision) =>
    apiFetch(`/admin/buyers/${id}/verify`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  resolveDispute: (id, data) =>
    apiFetch(`/admin/disputes/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

export function cents(v) {
  if (v == null) return '$0.00';
  return '$' + (v / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function shortDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}
