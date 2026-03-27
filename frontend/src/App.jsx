import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Sellers from './pages/Sellers';
import Buyers from './pages/Buyers';
import Lots from './pages/Lots';
import Orders from './pages/Orders';
import OrderDetail from './pages/OrderDetail';
import Disputes from './pages/Disputes';
import DisputeDetail from './pages/DisputeDetail';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/sellers" element={<Sellers />} />
          <Route path="/buyers" element={<Buyers />} />
          <Route path="/lots" element={<Lots />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/orders/:orderId" element={<OrderDetail />} />
          <Route path="/disputes" element={<Disputes />} />
          <Route path="/disputes/:disputeId" element={<DisputeDetail />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
