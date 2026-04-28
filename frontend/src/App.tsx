import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';

import DashboardPage from '@/pages/DashboardPage';
import TrackingPage from '@/pages/TrackingPage';
import RiskPage from '@/pages/RiskPage';
import RoutesPage from '@/pages/RoutesPage';
import AnalyticsPage from '@/pages/AnalyticsPage';
import ReportsPage from '@/pages/ReportsPage';
import CopilotPage from '@/pages/CopilotPage';
import SettingsPage from '@/pages/SettingsPage';
import BillingPage from '@/pages/BillingPage';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="tracking" element={<TrackingPage />} />
          <Route path="risk" element={<RiskPage />} />
          <Route path="routes" element={<RoutesPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="copilot" element={<CopilotPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="billing" element={<BillingPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}