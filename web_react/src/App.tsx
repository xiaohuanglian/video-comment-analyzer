import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import CollectPage from './pages/CollectPage'
import InsightPage from './pages/InsightPage'
import AutomationPage from './pages/AutomationPage'
import ProfilesPage from './pages/ProfilesPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<CollectPage />} />
          <Route path="collect" element={<CollectPage />} />
          <Route path="insight" element={<InsightPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="profiles" element={<ProfilesPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
