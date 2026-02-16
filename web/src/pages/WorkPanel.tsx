import { useState, useEffect, useCallback, useMemo } from 'react'
import type { Agent, Job, ShopItem, AgentItem } from '../types'
import { fetchJobs, checkIn, fetchShopItems, purchaseItem, fetchAgentItems } from '../api'

interface WorkPanelProps {
  agents: Agent[]
  onCreditsChange?: () => void
}

type Tab = 'jobs' | 'shop' | 'inventory'
const TAB_LABELS: Record<Tab, string> = { jobs: '岗位', shop: '商店', inventory: '背包' }

export function WorkPanel({ agents, onCreditsChange }: WorkPanelProps) {
  const [tab, setTab] = useState<Tab>('jobs')
  const [jobs, setJobs] = useState<Job[]>([])
  const [items, setItems] = useState<ShopItem[]>([])
  const [ownedItems, setOwnedItems] = useState<AgentItem[]>([])
  const [selectedAgent, setSelectedAgent] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const nonHumanAgents = useMemo(() => agents.filter(a => a.id !== 0), [agents])
  const currentAgent = agents.find(a => a.id === selectedAgent)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      if (tab === 'jobs') {
        setJobs(await fetchJobs())
      } else if (tab === 'shop') {
        setItems(await fetchShopItems())
      } else if (tab === 'inventory' && selectedAgent > 0) {
        setOwnedItems(await fetchAgentItems(selectedAgent))
      }
    } catch {
      setError('加载失败')
    } finally {
      setLoading(false)
    }
  }, [tab, selectedAgent])

  useEffect(() => { loadData() }, [loadData])

  // 默认选中第一个非人类 agent
  useEffect(() => {
    if (selectedAgent === 0 && nonHumanAgents.length > 0) {
      setSelectedAgent(nonHumanAgents[0].id)
    }
  }, [nonHumanAgents.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // 自动清除提示消息
  useEffect(() => {
    if (!message) return
    const t = setTimeout(() => setMessage(''), 3000)
    return () => clearTimeout(t)
  }, [message])

  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(''), 3000)
    return () => clearTimeout(t)
  }, [error])

  const handleCheckIn = async (jobId: number) => {
    if (selectedAgent <= 0) return
    setMessage('')
    setError('')
    try {
      const result = await checkIn(jobId, selectedAgent)
      if (result.ok) {
        setMessage(`打卡成功！获得 ${result.reward} 信用点`)
        onCreditsChange?.()
        loadData()
      } else {
        const reasons: Record<string, string> = {
          already_checked_in: '今日已打卡',
          job_full: '岗位已满',
          agent_not_found: 'Agent 不存在',
        }
        setError(reasons[result.reason] ?? result.reason)
      }
    } catch {
      setError('打卡失败')
    }
  }

  const handlePurchase = async (itemId: number) => {
    if (selectedAgent <= 0) return
    setMessage('')
    setError('')
    try {
      const result = await purchaseItem(selectedAgent, itemId)
      if (result.ok) {
        setMessage(`购买成功！花费 ${result.price} 信用点，剩余 ${result.remaining_credits}`)
        onCreditsChange?.()
        loadData()
      } else {
        const reasons: Record<string, string> = {
          insufficient_credits: '余额不足',
          already_owned: '已拥有该物品',
          agent_not_found: 'Agent 不存在',
          item_not_found: '商品不存在',
        }
        setError(reasons[result.reason] ?? result.reason)
      }
    } catch {
      setError('购买失败')
    }
  }

  return (
    <div className="work-panel">
      <div className="wp-header">
        <h2>城市经济</h2>
        <div className="wp-agent-select">
          <label>当前 Agent：</label>
          <select
            value={selectedAgent}
            onChange={e => setSelectedAgent(Number(e.target.value))}
          >
            <option value={0} disabled>选择 Agent...</option>
            {nonHumanAgents.map(a => (
              <option key={a.id} value={a.id}>{a.name} ({a.credits} 信用点)</option>
            ))}
          </select>
        </div>
      </div>

      <div className="wp-tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map(t => (
          <button
            key={t}
            className={`wp-tab ${tab === t ? 'active' : ''}`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {message && <div className="wp-success">{message}</div>}
      {error && <div className="form-error">{error}</div>}

      {loading ? (
        <div className="am-loading">加载中...</div>
      ) : selectedAgent <= 0 ? (
        <div className="am-empty">请先选择一个 Agent</div>
      ) : tab === 'jobs' ? (
        <div className="wp-list">
          {jobs.map(job => (
            <div key={job.id} className="wp-card">
              <div className="wp-card-header">
                <span className="wp-title">{job.title}</span>
                <span className="wp-reward">+{job.daily_reward} 信用点</span>
              </div>
              <div className="wp-desc">{job.description}</div>
              <div className="wp-card-footer">
                <span className="wp-capacity">
                  {job.today_workers}/{job.max_workers === 0 ? '∞' : job.max_workers} 在岗
                </span>
                <button
                  className="wp-action-btn"
                  onClick={() => handleCheckIn(job.id)}
                  disabled={job.max_workers > 0 && job.today_workers >= job.max_workers}
                >
                  打卡
                </button>
              </div>
            </div>
          ))}
          {jobs.length === 0 && <div className="am-empty">暂无岗位</div>}
        </div>
      ) : tab === 'shop' ? (
        <div className="wp-list">
          {items.map(item => (
            <div key={item.id} className="wp-card">
              <div className="wp-card-header">
                <span className="wp-title">{item.name}</span>
                <span className="wp-price">{item.price} 信用点</span>
              </div>
              <div className="wp-desc">{item.description}</div>
              <div className="wp-card-footer">
                <span className="wp-type">
                  {item.item_type === 'avatar_frame' ? '头像框' : item.item_type === 'title' ? '称号' : '装饰品'}
                </span>
                <button
                  className="wp-action-btn"
                  onClick={() => handlePurchase(item.id)}
                  disabled={!currentAgent || currentAgent.credits < item.price}
                >
                  购买
                </button>
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="am-empty">暂无商品</div>}
        </div>
      ) : (
        <div className="wp-list">
          {ownedItems.map(item => (
            <div key={item.item_id} className="wp-card wp-owned">
              <div className="wp-card-header">
                <span className="wp-title">{item.name}</span>
                <span className="wp-type">
                  {item.item_type === 'avatar_frame' ? '头像框' : item.item_type === 'title' ? '称号' : '装饰品'}
                </span>
              </div>
              <div className="wp-desc">购买于 {item.purchased_at}</div>
            </div>
          ))}
          {ownedItems.length === 0 && <div className="am-empty">背包空空如也</div>}
        </div>
      )}
    </div>
  )
}
