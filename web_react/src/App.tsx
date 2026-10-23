import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import CollectPage from './pages/CollectPage'
import WeChatPage from './pages/WeChatPage'
import AutomationPage from './pages/AutomationPage'
import TopicsPage from './pages/TopicsPage'
import WriterPage from './pages/WriterPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="collect" element={<CollectPage />} />
          <Route path="wechat" element={<WeChatPage />} />
          <Route path="automation" element={<AutomationPage />} />
          <Route path="topics" element={<TopicsPage />} />
          <Route path="writer" element={<WriterPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
