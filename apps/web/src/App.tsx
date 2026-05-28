import { Navigate, Route, Routes } from 'react-router-dom'
import { WorkbenchPage } from './pages/WorkbenchPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/workbench" replace />} />
      <Route path="/workbench" element={<WorkbenchPage />} />
      <Route path="/workbench/:runId" element={<WorkbenchPage />} />
      <Route path="/runs" element={<WorkbenchPage />} />
      <Route path="/runs/:runId" element={<WorkbenchPage />} />
    </Routes>
  )
}
