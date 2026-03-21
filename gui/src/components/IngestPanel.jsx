import { useState, useRef } from 'react'
import { useAuth } from '../context/AuthContext'

const API_BASE = import.meta.env.VITE_API_BASE || ''

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function PreviewModal({ preview, diff, llmAnalysis, isNew, isUpdated, onConfirm, onCancel, source }) {
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[85vh] flex flex-col">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-gray-900 text-sm">Preview &mdash; {source}</h2>
            <span className={`text-xs px-2 py-0.5 rounded-full mt-1 inline-block ${
              isNew ? 'bg-green-100 text-green-700' :
              isUpdated ? 'bg-yellow-100 text-yellow-700' :
              'bg-gray-100 text-gray-600'
            }`}>
              {isNew ? 'New document' : isUpdated ? 'Updated \u2014 changes detected' : 'Unchanged'}
            </span>
          </div>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">&times;</button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Content preview */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Content Preview</h3>
            <pre className="bg-gray-50 rounded border border-gray-200 p-3 text-xs text-gray-700 whitespace-pre-wrap font-mono max-h-48 overflow-y-auto">
              {preview || 'No preview available'}
            </pre>
          </div>

          {/* Breaking changes */}
          {isUpdated && llmAnalysis && (
            <div>
              <h3 className="text-xs font-semibold text-orange-600 uppercase mb-2">&#9888; Breaking Changes Analysis</h3>
              <div className="bg-orange-50 border border-orange-200 rounded p-3 text-xs text-orange-900">
                {llmAnalysis}
              </div>
            </div>
          )}

          {/* Raw diff */}
          {isUpdated && diff && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Raw Diff (first 1000 chars)</h3>
              <pre className="bg-gray-900 text-green-400 rounded p-3 text-xs font-mono overflow-x-auto max-h-40 overflow-y-auto">
                {diff}
              </pre>
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-200 flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-500"
          >
            Ingest &amp; Store
          </button>
        </div>
      </div>
    </div>
  )
}

export default function IngestPanel() {
  const { token } = useAuth()
  const [url, setUrl]           = useState('')
  const [tags, setTags]         = useState('')
  const [status, setStatus]     = useState('')
  const [loading, setLoading]   = useState(false)
  const [pendingJob, setPendingJob] = useState(null) // {job_id, type, preview, diff, llmAnalysis, isNew, isUpdated, source}
  const [docs, setDocs]         = useState([])
  const [docsLoaded, setDocsLoaded] = useState(false)
  const fileInputRef = useRef(null)

  const tagList = () => tags.split(',').map(t => t.trim()).filter(Boolean)

  const loadDocs = async () => {
    try {
      const r = await fetch(`${API_BASE}/api/memory/ingest/docs`, { headers: authHeaders(token) })
      if (r.ok) {
        const data = await r.json()
        setDocs(data.docs || [])
        setDocsLoaded(true)
      }
    } catch (e) {}
  }

  const handleUrlPreview = async () => {
    if (!url.trim()) return
    setLoading(true)
    setStatus('Fetching URL\u2026')
    try {
      const r = await fetch(`${API_BASE}/api/memory/ingest/url/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify({ url: url.trim(), tags: tagList() }),
      })
      const data = await r.json()
      if (!r.ok) { setStatus(`Error: ${data.detail || r.statusText}`); return }
      setPendingJob({
        job_id: data.job_id, type: 'url',
        preview: data.preview, diff: data.diff_snippet,
        llmAnalysis: data.breaking_changes_llm,
        isNew: data.is_new, isUpdated: data.is_updated,
        source: url.trim(),
      })
      setStatus('')
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirm = async () => {
    if (!pendingJob) return
    setLoading(true)
    setStatus('Storing\u2026')
    const endpoint = pendingJob.type === 'url'
      ? '/api/memory/ingest/url/confirm'
      : '/api/memory/ingest/pdf/confirm'
    try {
      const r = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify({ job_id: pendingJob.job_id, approved: true }),
      })
      const data = await r.json()
      if (r.ok) {
        setStatus(`\u2713 ${data.message || 'Stored successfully'}`)
        setUrl('')
        setPendingJob(null)
        loadDocs()
      } else {
        setStatus(`Error: ${data.detail || r.statusText}`)
        setPendingJob(null)
      }
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async () => {
    if (pendingJob) {
      const endpoint = pendingJob.type === 'url'
        ? '/api/memory/ingest/url/confirm'
        : '/api/memory/ingest/pdf/confirm'
      fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
        body: JSON.stringify({ job_id: pendingJob.job_id, approved: false }),
      }).catch(() => {})
    }
    setPendingJob(null)
    setStatus('')
  }

  const handleFileUpload = async (file) => {
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      setStatus('Only PDF files supported')
      return
    }
    setLoading(true)
    setStatus('Parsing PDF\u2026')
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('tags', tags)
      const r = await fetch(`${API_BASE}/api/memory/ingest/pdf/upload`, {
        method: 'POST',
        headers: authHeaders(token),
        body: formData,
      })
      const data = await r.json()
      if (!r.ok) { setStatus(`Error: ${data.detail || r.statusText}`); return }
      setPendingJob({
        job_id: data.job_id, type: 'pdf',
        preview: data.preview, diff: data.diff_snippet,
        llmAnalysis: data.breaking_changes_llm,
        isNew: data.is_new, isUpdated: data.is_updated,
        source: file.name,
      })
      setStatus('')
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleFileUpload(file)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {pendingJob && (
        <PreviewModal
          preview={pendingJob.preview}
          diff={pendingJob.diff}
          llmAnalysis={pendingJob.llmAnalysis}
          isNew={pendingJob.isNew}
          isUpdated={pendingJob.isUpdated}
          source={pendingJob.source}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      )}

      <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
        <h2 className="text-sm font-semibold text-gray-900">Document Ingestion</h2>
        <p className="text-xs text-gray-500 mt-0.5">Feed URLs or PDFs to the research agent&apos;s memory</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Tags */}
        <div>
          <label className="text-xs text-gray-500 uppercase font-semibold">Tags (comma separated)</label>
          <input
            type="text"
            value={tags}
            onChange={e => setTags(e.target.value)}
            placeholder="kafka, documentation, runbook"
            className="mt-1 w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
          />
        </div>

        {/* URL input */}
        <div>
          <label className="text-xs text-gray-500 uppercase font-semibold">URL</label>
          <div className="flex gap-2 mt-1">
            <input
              type="url"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleUrlPreview()}
              placeholder="https://..."
              className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-400"
            />
            <button
              onClick={handleUrlPreview}
              disabled={loading || !url.trim()}
              className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50"
            >
              {loading ? '\u2026' : 'Preview'}
            </button>
          </div>
        </div>

        {/* PDF drop zone */}
        <div>
          <label className="text-xs text-gray-500 uppercase font-semibold">PDF Upload</label>
          <div
            className="mt-1 border-2 border-dashed border-gray-300 rounded-lg p-6 text-center cursor-pointer hover:border-blue-400 transition-colors"
            onDrop={handleDrop}
            onDragOver={e => e.preventDefault()}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="text-gray-400 text-sm">Drop PDF here or click to upload</div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={e => e.target.files[0] && handleFileUpload(e.target.files[0])}
            />
          </div>
        </div>

        {/* Status */}
        {status && (
          <div className={`text-xs px-3 py-2 rounded ${
            status.startsWith('\u2713') ? 'bg-green-50 text-green-700' :
            status.startsWith('Error') ? 'bg-red-50 text-red-700' :
            'bg-blue-50 text-blue-700'
          }`}>
            {status}
          </div>
        )}

        {/* Stored docs */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-gray-500 uppercase font-semibold">Stored Documents</label>
            <button
              onClick={loadDocs}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              {docsLoaded ? 'Refresh' : 'Load'}
            </button>
          </div>
          {docsLoaded && docs.length === 0 && (
            <div className="text-xs text-gray-400">No documents stored yet.</div>
          )}
          <div className="space-y-1.5">
            {docs.map(doc => (
              <div key={doc.source_key} className="border border-gray-200 rounded px-3 py-2 bg-white">
                <div className="text-xs font-medium text-gray-800 truncate">{doc.source_label}</div>
                <div className="text-xs text-gray-400 mt-0.5">
                  {doc.chunk_count} chunks &middot; {doc.stored_at ? new Date(doc.stored_at).toLocaleDateString() : ''}
                  {doc.source_url && (
                    <span className="ml-2 text-blue-500 truncate">{doc.source_url.slice(0, 50)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
