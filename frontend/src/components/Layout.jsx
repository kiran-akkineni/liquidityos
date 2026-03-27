import { NavLink, Outlet } from 'react-router-dom';

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/sellers', label: 'Sellers' },
  { to: '/buyers', label: 'Buyers' },
  { to: '/lots', label: 'Lots' },
  { to: '/orders', label: 'Orders' },
  { to: '/disputes', label: 'Disputes' },
];

export default function Layout() {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <nav className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-8">
        <span className="text-lg font-semibold text-white tracking-tight">
          LiquidityOS
        </span>
        <div className="flex gap-1">
          {links.map(l => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.to === '/'}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
        </div>
        <span className="ml-auto text-xs text-gray-500">ops_admin</span>
      </nav>
      <main className="p-6 max-w-7xl mx-auto">
        <Outlet />
      </main>
    </div>
  );
}
