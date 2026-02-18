import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { fetchCityOverview, transferResource } from '../api'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CityAgentStatus, WsIncoming } from '../types'
import './TradePage.css'

interface TransferLog {
  id: number
  fromName: string
  toName: string
  resourceType: string
  quantity: number
  time: string
}

let logIdCounter = 0

export function TradePage() {
  const [agents, setAgents] = useState<CityAgentStatus[]>([])
  const [fromId, setFromId] = useState<number | ''>('')
  const [toId, setToId] = useState<number | ''>('')
  const [resourceType, setResourceType] = useState('flour')
  const [quantity, setQuantity] = useState<number | ''>('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null)
  const [history, setHistory] = useState<TransferLog[]>([])

  const loadAgents = useCallback(async () => {
    try {
      const data = await fetchCityOverview('长安')
      setAgents(data.agents ?? [])
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    loadAgents()
  }, [loadAgents])

  // WebSocket: 监听 resource_transferred 事件
  const handleWs = useCallback((msg: WsIncoming) => {
    if (msg.type === 'system_event' && msg.data.event === 'resource_transferred') {
      const d = msg.data
      setHistory(prev => {
        const entry: TransferLog = {
          id: ++logIdCounter,
          fromName: d.from_agent_name ?? `Agent#${d.from_agent_id}`,
          toName: d.to_agent_name ?? `Agent#${d.to_agent_id}`,
          resourceType: d.resource_type ?? '?',
          quantity: d.quantity ?? 0,
          time: new Date(d.timestamp).toLocaleTimeString(),
        }
        const next = [entry, ...prev]
        return next.length > 50 ? next.slice(0, 50) : next
      })
      // 刷新资源概览
      loadAgents()
    }
  }, [loadAgents])

  useWebSocket(handleWs)

  const handleSubmit = async () => {
    if (fromId === '' || toId === '' || !quantity || quantity <= 0) return
    if (fromId === toId) {
      setMessage({ text: '不能转赠给自己', ok: false })
      return
    }
    setSubmitting(true)
    setMessage(null)
    try {
      const res = await transferResource(fromId, toId, resourceType, quantity)
      setMessage({ text: res.reason, ok: res.ok })
      setTimeout(() => setMessage(null), 3000)
      if (res.ok) {
        setQuantity('')
        loadAgents()
      }
    } catch (e) {
      setMessage({ text: String(e), ok: false })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setSubmitting(false)
    }
  }

  // 收集所有出现过的资源类型
  const resourceTypes = [...new Set(
    agents.flatMap(a => a.resources.map(r => r.resource_type))
  )]
  if (!resourceTypes.includes('flour')) resourceTypes.unshift('flour')

  return (
    <div className="trade-page">
      <div className="tp-header">
        <Link to="/" className="tp-back-btn" aria-label="返回主界面">← 返回</Link>
        <h2>资源交易面板</h2>
      </div>

      <div className="tp-section-title">居民资源概览</div>
      <div className="tp-agent-resources">
        {agents.map(a => (
          <div key={a.id} className="tp-agent-row">
            <span className="tp-agent-name">{a.name}</span>
            <span className="tp-agent-res">
              {a.resources.length > 0
                ? a.resources.map(r => `${r.resource_type}=${r.quantity}`).join(', ')
                : '无资源'}
            </span>
          </div>
        ))}
      </div>

      <div className="tp-section-title">转赠资源</div>
      <div className="tp-form" role="form" aria-label="资源转赠表单">
        <label>
          发送方
          <select
            value={fromId}
            onChange={e => setFromId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">选择居民</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        <label>
          接收方
          <select
            value={toId}
            onChange={e => setToId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">选择居民</option>
            {agents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
        <label>
          资源类型
          <select value={resourceType} onChange={e => setResourceType(e.target.value)}>
            {resourceTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label>
          数量
          <input
            type="number"
            min={1}
            value={quantity}
            onChange={e => setQuantity(e.target.value ? Number(e.target.value) : '')}
          />
        </label>
        <div className="tp-submit-row">
          <button
            className="tp-submit-btn"
            disabled={submitting || fromId === '' || toId === '' || !quantity}
            onClick={handleSubmit}
          >
            {submitting ? '转赠中...' : '转赠'}
          </button>
          {message && (
            <span className={`tp-message ${message.ok ? 'success' : 'error'}`}>
              {message.text}
            </span>
          )}
        </div>
      </div>

      <div className="tp-section-title">转赠历史（实时）</div>
      <div className="tp-history" aria-live="polite">
        {history.length === 0 ? (
          <div className="tp-history-empty">暂无转赠记录</div>
        ) : (
          history.map(h => (
            <div key={h.id} className="tp-history-item">
              <span className="tp-history-time">{h.time}</span>
              <span>{h.fromName} → {h.toName}: {h.quantity} {h.resourceType}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
