import { useCallback, useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const FILTERS = ['all', 'critical', 'high', 'medium', 'info']
const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'details', label: 'Incident Details' },
  { id: 'automation', label: 'Automation & Runbook' },
  { id: 'chaos', label: 'Chaos Drill' },
]

const SIGNAL_CONFIG = {
  error_rate: {
    severity: 'critical',
    title: 'Error Rate Breach',
    explanation: 'Payment failures are above tolerance and customer transactions are at risk.',
    traceHints: ['http_error', 'payment_error'],
  },
  p95_latency: {
    severity: 'medium',
    title: 'Latency SLO Breach',
    explanation: 'P95 response time is above expected checkout latency SLO.',
    traceHints: ['http_request'],
  },
  timeout_count: {
    severity: 'high',
    title: 'Timeout Storm',
    explanation: 'Downstream dependencies are timing out and can trigger cascading failures.',
    traceHints: ['downstream_timeout', 'timeout'],
  },
  db_pool_exhausted_count: {
    severity: 'high',
    title: 'DB Pool Saturation',
    explanation: 'Database connection pool pressure is limiting payment throughput.',
    traceHints: ['db_pool_exhausted'],
  },
}

const SEVERITY_ORDER = { critical: 1, high: 2, medium: 3, info: 4 }

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${text}`)
  }
  return response.json()
}

function toList(value) {
  if (!Array.isArray(value)) return []
  return value.filter(Boolean)
}

function parseAiSummary(summary) {
  if (!summary) return []
  return String(summary)
    .split(/\n\n+/)
    .map((chunk) => chunk.trim())
    .filter(Boolean)
}

function formatDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function buildAlertCards(data, automationResult) {
  if (!data) return []

  const cards = []
  const generatedAt = data.generated_at || new Date().toISOString()
  const requestsTotal = Number(data.requests_total || 0)
  const errorRate = Number(data.error_rate_percent || 0)
  const p95 = Number(data.p95_latency_seconds || 0)

  if (data.incident_likely) {
    cards.push({
      id: 'incident-active',
      severity: 'critical',
      source: 'detector',
      title: data.scenario || 'Incident likely active',
      detail: `Error rate ${errorRate.toFixed(2)}% with ${data.recent_error_count || 0} recent failures.`,
      action: data.recommended_remediation || 'Stabilize traffic and validate dependencies.',
      traceHints: ['http_error', 'payment_error', 'timeout', 'db_pool_exhausted'],
      timestamp: generatedAt,
    })
  }

  for (const signal of data.breached_signals || []) {
    const cfg = SIGNAL_CONFIG[signal] || {
      severity: 'medium',
      title: signal,
      explanation: 'Threshold breached. Requires investigation.',
      traceHints: ['http_error'],
    }

    cards.push({
      id: `signal-${signal}`,
      severity: cfg.severity,
      source: 'signal',
      title: cfg.title,
      detail: cfg.explanation,
      action: 'Inspect metrics trend, related logs, and recent deployment/config changes.',
      traceHints: cfg.traceHints,
      timestamp: generatedAt,
    })
  }

  for (const failure of data.failure_types || []) {
    cards.push({
      id: `failure-${failure.type}`,
      severity: failure.count >= 20 ? 'critical' : failure.count >= 5 ? 'high' : 'medium',
      source: 'telemetry',
      title: `Failure pattern: ${failure.type}`,
      detail: `${failure.count} occurrences in recent telemetry window.`,
      action: 'Correlate with traces and backend dependency behavior before remediation.',
      traceHints: [failure.type],
      timestamp: generatedAt,
    })
  }

  if (requestsTotal > 400) {
    cards.push({
      id: 'traffic-surge',
      severity: 'high',
      source: 'capacity',
      title: 'Traffic Surge Detected',
      detail: `Request volume is elevated (${requestsTotal.toFixed(0)} requests) and could amplify failure impact.`,
      action: 'Scale worker capacity and validate dependency saturation limits.',
      traceHints: ['http_request'],
      timestamp: generatedAt,
    })
  }

  if (data.ai_mocked) {
    cards.push({
      id: 'ai-fallback-mode',
      severity: 'high',
      source: 'ai',
      title: 'AI Fallback Mode Active',
      detail: 'Claude incident analysis is unavailable; mocked summaries are being used.',
      action: 'Verify CLAUDE_API_KEY and API reachability to restore live AI RCA.',
      traceHints: ['claude_summary_failed'],
      timestamp: generatedAt,
    })
  }

  if (data.incident_likely && !automationResult) {
    cards.push({
      id: 'automation-recommended',
      severity: 'medium',
      source: 'workflow',
      title: 'Automation Pending',
      detail: 'Incident is active but automation/runbook update has not run yet.',
      action: 'Run automation to generate RCA, notify Slack, and update runbook.',
      traceHints: ['http_error', 'timeout', 'db_pool_exhausted'],
      timestamp: generatedAt,
    })
  }

  if (errorRate > 0 && errorRate < 2 && p95 < 0.2 && !data.incident_likely) {
    cards.push({
      id: 'low-grade-errors',
      severity: 'info',
      source: 'quality',
      title: 'Low-Grade Errors Present',
      detail: 'Small background error rate is present despite healthy incident status.',
      action: 'Review non-critical failures during business hours to prevent drift.',
      traceHints: ['http_error'],
      timestamp: generatedAt,
    })
  }

  const ai = automationResult?.analysis?.analysis
  if (ai?.likely_root_cause) {
    cards.push({
      id: 'ai-rca',
      severity: 'info',
      source: 'claude',
      title: `AI RCA: ${ai.impacted_component || 'Component identified'}`,
      detail: ai.likely_root_cause,
      action: toList(ai.immediate_remediation_steps).slice(0, 2).join(' | ') || 'Review AI remediation plan.',
      traceHints: ['http_error', 'downstream_timeout', 'db_pool_exhausted'],
      timestamp: generatedAt,
    })
  }

  return cards.sort((a, b) => {
    const rank = (SEVERITY_ORDER[a.severity] || 99) - (SEVERITY_ORDER[b.severity] || 99)
    if (rank !== 0) return rank
    return a.title.localeCompare(b.title)
  })
}

function findRelatedLogs(data, selectedAlert) {
  if (!data || !selectedAlert) return []
  const hints = selectedAlert.traceHints || []
  const logs = data.recent_log_evidence || []

  return logs
    .filter((entry) => {
      const event = String(entry.event || '').toLowerCase()
      const type = String(entry.error_type || '').toLowerCase()
      return hints.some((hint) => event.includes(hint.toLowerCase()) || type.includes(hint.toLowerCase()))
    })
    .slice(0, 10)
}

function countBySeverity(cards) {
  return cards.reduce(
    (acc, card) => {
      acc[card.severity] = (acc[card.severity] || 0) + 1
      return acc
    },
    { critical: 0, high: 0, medium: 0, info: 0 },
  )
}

function KpiCard({ label, value, hint }) {
  return (
    <article className="kpi-card">
      <p>{label}</p>
      <h3>{value}</h3>
      <span>{hint}</span>
    </article>
  )
}

export default function App() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [actionMessage, setActionMessage] = useState('')
  const [automationResult, setAutomationResult] = useState(null)
  const [chaosResult, setChaosResult] = useState(null)
  const [selectedAlertId, setSelectedAlertId] = useState('')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [activeTab, setActiveTab] = useState('alerts')
  const [autoNotifyCritical, setAutoNotifyCritical] = useState(true)
  const [autoRunbookUpdate, setAutoRunbookUpdate] = useState(false)
  const [lastCriticalSignature, setLastCriticalSignature] = useState('')
  const [lastAutoRunbookSignature, setLastAutoRunbookSignature] = useState('')
  const [showLogs, setShowLogs] = useState(false)
  const [showRunbook, setShowRunbook] = useState(false)
  const [showResolvePanel, setShowResolvePanel] = useState(false)
  const [resolutionActionsText, setResolutionActionsText] = useState('')
  const [resolutionNotes, setResolutionNotes] = useState('')
  const [resolutionMarkedAt, setResolutionMarkedAt] = useState('')
  const [incidentView, setIncidentView] = useState('active')
  const [resolvedIncidents, setResolvedIncidents] = useState([])

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const payload = await fetchJson(`${API_BASE}/dashboard/data`)
      setData(payload)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDashboard()
    const timer = setInterval(loadDashboard, 15000)
    return () => clearInterval(timer)
  }, [loadDashboard])

  const cards = useMemo(() => buildAlertCards(data, automationResult), [data, automationResult])
  const severityCounts = useMemo(() => countBySeverity(cards), [cards])

  const activeCards = useMemo(() => {
    if (severityFilter === 'all') return cards
    return cards.filter((card) => card.severity === severityFilter)
  }, [cards, severityFilter])

  const resolvedCards = useMemo(() => {
    if (severityFilter === 'all') return resolvedIncidents
    return resolvedIncidents.filter((card) => card.severity === severityFilter)
  }, [resolvedIncidents, severityFilter])

  const cardsForView = incidentView === 'resolved' ? resolvedCards : activeCards
  const viewSeverityCounts = useMemo(() => countBySeverity(cardsForView), [cardsForView])

  useEffect(() => {
    if (!cardsForView.length) {
      setSelectedAlertId('')
      return
    }
    const stillVisible = cardsForView.some((card) => card.id === selectedAlertId)
    if (!stillVisible) setSelectedAlertId(cardsForView[0].id)
  }, [cardsForView, selectedAlertId])

  const selectedAlert = useMemo(
    () => cardsForView.find((card) => card.id === selectedAlertId) || null,
    [cardsForView, selectedAlertId],
  )

  const relatedLogs = useMemo(() => findRelatedLogs(data, selectedAlert), [data, selectedAlert])

  const aiSections = useMemo(
    () => parseAiSummary(data?.latest_ai_incident_summary || automationResult?.analysis?.summary_text),
    [data, automationResult],
  )

  const remediationSteps = useMemo(() => {
    const selected = selectedAlert?.action ? [selectedAlert.action] : []
    const baseline = data?.recommended_remediation ? [data.recommended_remediation] : []
    const immediate = toList(automationResult?.analysis?.analysis?.immediate_remediation_steps)
    const longTerm = toList(automationResult?.analysis?.analysis?.long_term_prevention_actions)
    return [...selected, ...baseline, ...immediate, ...longTerm].filter(Boolean).slice(0, 10)
  }, [selectedAlert, data, automationResult])

  const runbookInfo = automationResult?.runbook_update

  useEffect(() => {
    if (!showResolvePanel) return
    if (resolutionActionsText.trim()) return

    const defaultActions = remediationSteps.length
      ? remediationSteps.map((step, index) => `${index + 1}. ${step}`).join('\n')
      : '1. Validate error rate and latency recovered to baseline.\n2. Verify downstream dependencies and DB pools are stable.\n3. Document final fix and owner handoff in runbook.'

    setResolutionActionsText(defaultActions)
  }, [showResolvePanel, remediationSteps, resolutionActionsText])

  const notifySlack = useCallback(async (reason = 'manual') => {
    const result = await fetchJson(`${API_BASE}/notifications/slack/incident`, { method: 'POST' })
    if (result.notification?.mocked) {
      setActionMessage(`Slack mocked (${reason}): ${result.notification.reason}`)
      return
    }
    setActionMessage(`Slack notification sent (${reason})`)
  }, [])

  const runAutomationForAlert = useCallback(
    async (alert, reason = 'manual') => {
      const payload = {
        source: 'frontend-dashboard',
        severity: alert.severity,
        alert_name: alert.title.toLowerCase().replace(/\s+/g, '_'),
        description: `${alert.detail} [reason=${reason}]`,
        labels: { team: 'sre', service: 'payment-api', alert_card: alert.id },
        annotations: { summary: `Alert selected in UI: ${alert.title}` },
      }

      const response = await fetchJson(`${API_BASE}/alerts/webhook`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      setAutomationResult(response.result)
      await loadDashboard()
      return response.result
    },
    [loadDashboard],
  )

  useEffect(() => {
    if (!autoNotifyCritical || !data) return
    const critical = cards.find((card) => card.severity === 'critical')
    if (!critical) return

    const signature = `${data.generated_at}-${critical.id}`
    if (signature === lastCriticalSignature) return

    notifySlack('auto-critical').catch((err) => {
      setActionMessage(`Auto Slack failed: ${err.message}`)
    })
    setLastCriticalSignature(signature)
  }, [autoNotifyCritical, cards, data, lastCriticalSignature, notifySlack])

  useEffect(() => {
    if (!autoRunbookUpdate || !data || !data.incident_likely || !selectedAlert) return
    const signature = `${data.generated_at}-${selectedAlert.id}`
    if (signature === lastAutoRunbookSignature) return

    runAutomationForAlert(selectedAlert, 'auto-runbook')
      .then(() => setActionMessage(`Runbook auto-updated for ${selectedAlert.title}`))
      .catch((err) => setActionMessage(`Auto runbook update failed: ${err.message}`))

    setLastAutoRunbookSignature(signature)
  }, [autoRunbookUpdate, data, lastAutoRunbookSignature, runAutomationForAlert, selectedAlert])

  async function changeMode(mode) {
    setActionMessage(`Switching mode to ${mode}...`)
    try {
      await fetchJson(`${API_BASE}/simulate/${mode}`, { method: 'POST' })
      setActionMessage(`Mode switched to ${mode}`)
      await loadDashboard()
    } catch (err) {
      setActionMessage(`Mode switch failed: ${err.message}`)
    }
  }

  async function triggerAutomation() {
    const alert = selectedAlert || {
      id: 'manual-default',
      severity: 'critical',
      title: 'payment_api_anomaly_detected',
      detail: 'Triggered from dashboard without selected alert',
    }

    setActionMessage(`Running automation for ${alert.title}...`)

    try {
      await runAutomationForAlert(alert, 'manual')
      setActionMessage(`Automation completed for ${alert.title}`)
      setActiveTab('automation')
    } catch (err) {
      setActionMessage(`Automation failed: ${err.message}`)
    }
  }

  function markIncidentResolved() {
    setShowResolvePanel(true)
    setResolutionMarkedAt('')
    setActionMessage('Review AI suggested actions, update if needed, then confirm resolution.')
  }

  async function confirmIncidentResolved() {
    const alert = selectedAlert || {
      id: 'resolved-manual',
      severity: 'info',
      title: 'incident_resolved',
      detail: 'Incident marked as resolved from dashboard',
    }

    setActionMessage('Marking incident as resolved and updating runbook...')

    try {
      const notes = resolutionNotes.trim() || 'Resolved by dashboard operator.'
      const actions = resolutionActionsText.trim() || 'No action steps entered.'

      await runAutomationForAlert(
        {
          ...alert,
          severity: 'info',
          title: `resolved_${alert.title}`,
          detail: `Incident resolved. ${notes} Actions: ${actions}`,
        },
        'resolve',
      )

      const resolvedAt = new Date().toISOString()
      setResolvedIncidents((prev) => [
        {
          ...alert,
          id: `resolved-${alert.id}-${resolvedAt}`,
          severity: 'info',
          source: 'resolved',
          title: `Resolved: ${alert.title}`,
          detail: notes,
          action: actions.split('\n')[0] || 'Resolution completed and documented.',
          timestamp: resolvedAt,
        },
        ...prev,
      ])
      setResolutionMarkedAt(resolvedAt)
      setActionMessage('Incident marked resolved. Runbook updated.')
      setShowRunbook(true)
      setShowResolvePanel(false)
      setActiveTab('automation')
    } catch (err) {
      setActionMessage(`Resolve update failed: ${err.message}`)
    }
  }

  async function runChaosDrill() {
    setActionMessage('Starting Chaos Drill (~45-90s)...')
    try {
      const response = await fetchJson(`${API_BASE}/drill/chaos`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runbook_update: true }),
      })
      setChaosResult(response.result)
      setActionMessage('Chaos Drill completed')
      await loadDashboard()
      setActiveTab('chaos')
    } catch (err) {
      setActionMessage(`Chaos Drill failed: ${err.message}`)
    }
  }

  function handleAlertClick(card) {
    setSelectedAlertId(card.id)
    setActiveTab('details')
    setShowLogs(false)
  }

  async function copyAiSummary() {
    try {
      await navigator.clipboard.writeText(aiSections.join('\n\n') || 'No summary available')
      setActionMessage('AI summary copied')
    } catch {
      setActionMessage('Clipboard copy failed')
    }
  }

  return (
    <main className="cmd-page">
      <header className="cmd-header">
        <div>
          <p className="eyebrow">AI INCIDENT COMMANDER</p>
          <h1>Production Incident Command Console</h1>
          <p className="subtext">Initial view is alerts-only. Click an alert to open detailed investigation workflow.</p>
        </div>
        <div className="head-right">
          <span className={`status-pill ${data?.incident_likely ? 'critical' : 'healthy'}`}>
            {data?.incident_likely ? 'INCIDENT ACTIVE' : 'HEALTHY'}
          </span>
          <button className="btn ghost" onClick={loadDashboard} disabled={loading}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </header>

      <nav className="top-menu">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`menu-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {error && <div className="banner error">{error}</div>}
      {actionMessage && <div className="banner info">{actionMessage}</div>}

      <section className="kpi-grid">
        <KpiCard label="Incident Mode" value={data?.current_incident_mode || '-'} hint={data?.scenario || 'No scenario'} />
        <KpiCard label="Error Rate" value={`${Number(data?.error_rate_percent || 0).toFixed(2)}%`} hint="Critical signal" />
        <KpiCard label="p95 Latency" value={`${Number(data?.p95_latency_seconds || 0).toFixed(3)}s`} hint="SLO" />
        <KpiCard label="Recent Errors" value={String(data?.recent_error_count ?? 0)} hint="Failure volume" />
      </section>

      {activeTab === 'alerts' && (
        <section className="panel">
          <div className="panel-head">
            <h2>Alert Labels</h2>
            <div className="incident-view-toggle">
              <button
                className={`incident-view-btn active-view ${incidentView === 'active' ? 'selected' : ''}`}
                onClick={() => setIncidentView('active')}
              >
                Active Incidents ({cards.length})
              </button>
              <button
                className={`incident-view-btn resolved-view ${incidentView === 'resolved' ? 'selected' : ''}`}
                onClick={() => setIncidentView('resolved')}
              >
                Resolved Incidents ({resolvedIncidents.length})
              </button>
            </div>
            <div className="filters">
              {FILTERS.map((filter) => (
                <button
                  key={filter}
                  className={`chip ${severityFilter === filter ? 'active' : ''}`}
                  onClick={() => setSeverityFilter(filter)}
                >
                  {filter.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="severity-strip">
            <span className="severity-pill critical">Critical: {viewSeverityCounts.critical}</span>
            <span className="severity-pill high">High: {viewSeverityCounts.high}</span>
            <span className="severity-pill medium">Medium: {viewSeverityCounts.medium}</span>
            <span className="severity-pill info">Info: {viewSeverityCounts.info}</span>
          </div>

          {!cardsForView.length ? (
            <p className="muted">{incidentView === 'resolved' ? 'No resolved incidents yet.' : 'No active alerts in this filter.'}</p>
          ) : (
            <div className="alert-list">
              {cardsForView.map((card) => (
                <article
                  key={card.id}
                  className={`alert-card ${card.severity} ${card.source === 'resolved' ? 'resolved' : ''} ${selectedAlert?.id === card.id ? 'selected' : ''}`}
                  onClick={() => handleAlertClick(card)}
                >
                  <div className="alert-head">
                    <span className={`sev ${card.severity}`}>{card.severity}</span>
                    <span className={`source-chip ${card.source}`}>{card.source}</span>
                    <span>{formatDate(card.timestamp)}</span>
                  </div>
                  <h3>{card.title}</h3>
                  <p>{card.detail}</p>
                  <p className="next"><strong>Next:</strong> {card.action}</p>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {activeTab === 'details' && (
        <section className="details-grid">
          <article className="panel">
            <h2>Selected Alert & Related Metrics</h2>
            {selectedAlert ? (
              <div className={`selected-block ${selectedAlert.severity}`}>
                <h3>{selectedAlert.title}</h3>
                <p>{selectedAlert.detail}</p>
                <p><strong>Recommended step:</strong> {selectedAlert.action}</p>
              </div>
            ) : (
              <p className="muted">Go to Alerts tab and click an alert to investigate.</p>
            )}

            <div className="metrics-mini-grid">
              <div className="mini-box"><p>Error Rate</p><strong>{Number(data?.metrics_snapshot?.error_rate_percent || 0).toFixed(2)}%</strong></div>
              <div className="mini-box"><p>p95 Latency</p><strong>{Number(data?.metrics_snapshot?.payment_latency_p95_seconds || 0).toFixed(3)}s</strong></div>
              <div className="mini-box"><p>Timeout Total</p><strong>{Number(data?.metrics_snapshot?.timeout_total || 0).toFixed(0)}</strong></div>
              <div className="mini-box"><p>DB Exhausted</p><strong>{Number(data?.metrics_snapshot?.db_pool_exhausted_total || 0).toFixed(0)}</strong></div>
            </div>
          </article>

          <article className="panel">
            <div className="panel-head">
              <h2>Incident Summary</h2>
              <button className="btn summary" onClick={copyAiSummary}>Copy Summary</button>
            </div>
            {aiSections.length ? (
              <div className="summary-grid">
                {aiSections.map((part, idx) => (
                  <article key={`sum-${idx}`} className="summary-card"><p>{part}</p></article>
                ))}
              </div>
            ) : (
              <p className="muted">Run automation to generate AI summary.</p>
            )}
          </article>

          <article className="panel full-width">
            <div className="panel-head">
              <h2>Logs / Traces</h2>
              <button className="btn logs" onClick={() => setShowLogs((prev) => !prev)}>
                {showLogs ? 'Hide Logs' : 'Show Logs'}
              </button>
            </div>
            {!showLogs ? (
              <p className="muted">Logs are hidden. Click "Show Logs" to open related traces in the bottom panel.</p>
            ) : relatedLogs.length ? (
              <div className="trace-list">
                {relatedLogs.map((row, idx) => (
                  <div key={`trace-${idx}`} className="trace-item">
                    <p><strong>{row.event || 'event'}</strong> ({row.error_type || 'n/a'})</p>
                    <p>Status: {row.status || 'n/a'}</p>
                    <p>Time: {formatDate(row.timestamp)}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No directly matched logs yet for this alert.</p>
            )}
          </article>
        </section>
      )}

      {activeTab === 'automation' && (
        <section className="details-grid">
          <article className="panel">
            <h2>Automation Actions</h2>
            <label className="toggle">
              <input type="checkbox" checked={autoNotifyCritical} onChange={(e) => setAutoNotifyCritical(e.target.checked)} />
              Auto Slack on Critical Alert
            </label>
            <label className="toggle">
              <input type="checkbox" checked={autoRunbookUpdate} onChange={(e) => setAutoRunbookUpdate(e.target.checked)} />
              Auto Update Runbook While Incident Active
            </label>

            <div className="btn-stack">
              <button className="btn slack" onClick={() => notifySlack('manual')}>Send Slack Incident Notification</button>
              <button className="btn automation" onClick={triggerAutomation}>Run Automation for Selected Alert</button>
              <button className="btn resolve" onClick={markIncidentResolved}>Mark Incident Resolved</button>
              <button className="btn runbook" onClick={() => setShowRunbook((prev) => !prev)}>
                {showRunbook ? 'Hide Runbook' : 'Show Runbook'}
              </button>
            </div>
            {resolutionMarkedAt && (
              <p className="resolved-badge">
                Resolved at {formatDate(resolutionMarkedAt)}. Runbook and automation context captured.
              </p>
            )}
            <p className="muted">Automation uses selected alert context, updates runbook, and returns AI RCA.</p>
          </article>

          <article className="panel">
            <h2>Runbook</h2>
            {!showRunbook ? (
              <p className="muted">Runbook is hidden. Click "Show Runbook" to open runbook update details.</p>
            ) : runbookInfo ? (
              <div className="runbook-box">
                <p><strong>Runbook file:</strong> {runbookInfo.runbook_file || '-'}</p>
                <p><strong>History file:</strong> {runbookInfo.history_file || '-'}</p>
                <p><strong>Updated at:</strong> {formatDate(runbookInfo.updated_at)}</p>
              </div>
            ) : (
              <p className="muted">Run automation to generate runbook updates.</p>
            )}
          </article>

          {showResolvePanel && (
            <article className="panel full-width">
              <h2>Resolve Workflow</h2>
              <p className="muted">AI suggested actions are prefilled below. Edit steps and notes before confirming resolution.</p>
              <div className="resolve-grid">
                <div>
                  <label className="resolve-label">AI Suggested Actions</label>
                  <textarea
                    className="resolve-input"
                    value={resolutionActionsText}
                    onChange={(e) => setResolutionActionsText(e.target.value)}
                    rows={8}
                  />
                </div>
                <div>
                  <label className="resolve-label">Resolution Notes</label>
                  <textarea
                    className="resolve-input"
                    value={resolutionNotes}
                    onChange={(e) => setResolutionNotes(e.target.value)}
                    rows={8}
                    placeholder="What fixed the incident? Include owner, rollout, and verification."
                  />
                </div>
              </div>
              <div className="resolve-actions">
                <button className="btn confirm" onClick={confirmIncidentResolved}>
                  Confirm Resolve + Update Runbook
                </button>
                <button className="btn ghost" onClick={() => setShowResolvePanel(false)}>
                  Cancel
                </button>
              </div>
            </article>
          )}

          <article className="panel full-width">
            <h2>Automation Output (JSON)</h2>
            <pre>{automationResult ? JSON.stringify(automationResult, null, 2) : 'No automation output yet.'}</pre>
          </article>
        </section>
      )}

      {activeTab === 'chaos' && (
        <section className="details-grid">
          <article className="panel">
            <h2>Chaos Drill Controls</h2>
            <div className="btn-stack">
              <button className="btn" onClick={() => changeMode('normal')}>Normal</button>
              <button className="btn" onClick={() => changeMode('latency_spike')}>Latency Spike</button>
              <button className="btn" onClick={() => changeMode('timeout_storm')}>Timeout Storm</button>
              <button className="btn" onClick={() => changeMode('db_pool_exhausted')}>DB Pool Exhausted</button>
              <button className="btn" onClick={() => changeMode('error_spike')}>Error Spike</button>
              <button className="btn primary" onClick={runChaosDrill}>Run Full Chaos Drill</button>
            </div>
          </article>

          <article className="panel full-width">
            <h2>Chaos Drill Timeline</h2>
            {!chaosResult?.stages?.length ? (
              <p className="muted">No drill run recorded yet.</p>
            ) : (
              <div className="trace-list">
                {chaosResult.stages.map((stage) => (
                  <div key={stage.mode} className="trace-item">
                    <p><strong>{stage.mode}</strong></p>
                    <p>Requests: {stage?.load_summary?.total_requests ?? '-'}</p>
                    <p>Failures: {stage?.load_summary?.failed_requests ?? '-'}</p>
                    <p>p95 latency: {stage?.load_summary?.p95_latency_ms ?? '-'} ms</p>
                  </div>
                ))}
              </div>
            )}
          </article>
        </section>
      )}
    </main>
  )
}
