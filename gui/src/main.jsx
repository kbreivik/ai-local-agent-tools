import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

const path = window.location.pathname

if (path.startsWith('/subtask/')) {
  const sessionId = path.replace('/subtask/', '').split('/')[0]
  import('./components/SubtaskPopup.jsx').then(({ default: SubtaskPopup }) => {
    createRoot(document.getElementById('root')).render(
      <StrictMode>
        <SubtaskPopup sessionId={sessionId} />
      </StrictMode>
    )
  })
} else if (path.startsWith('/runbook/')) {
  const proposalId = path.replace('/runbook/', '').split('/')[0]
  import('./components/RunbookPopup.jsx').then(({ default: RunbookPopup }) => {
    createRoot(document.getElementById('root')).render(
      <StrictMode>
        <RunbookPopup proposalId={proposalId} />
      </StrictMode>
    )
  })
} else {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>
  )
}
