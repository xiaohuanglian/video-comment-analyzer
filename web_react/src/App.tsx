import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import GrowthPage from './pages/GrowthPage'
import CollectPage from './pages/CollectPage'
import InsightPage from './pages/InsightPage'
import WeChatPage from './pages/WeChatPage'
import AutomationPage from './pages/AutomationPage'
import TopicsPage from './pages/TopicsPage'
import WriterPage from './pages/WriterPage'
import StudioPage from './pages/StudioPage'
import PublishPage from './pages/PublishPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<GrowthPage />} />
          <Route path="assistant" element={<HomePage />} />
          <Route path="collect" element={<CollectPage />} />
          <Route path="insight" element={<InsightPage />} />
          <Route path="wechat" element={<WeChatPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="topics" element={<TopicsPage />} />
          <Route path="writer" element={<WriterPage />} />
          <Route path="studio" element={<StudioPage />} />
          <Route path="publish" element={<PublishPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
