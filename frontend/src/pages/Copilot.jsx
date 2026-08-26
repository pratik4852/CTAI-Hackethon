import React, { useEffect, useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  useChatHistoryQuery,
  useClearChatMutation,
  useSendChatMutation,
} from '../store/api'
import { toast } from '../store/uiSlice'
import EmptyState from '../components/EmptyState'
import { renderMarkdown } from '../lib/format'

function Message({ m }) {
  const tools = m.meta?.tool_calls || []
  return (
    <div className={`msg ${m.role}`}>
      <div dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }} />
      {m.role === 'assistant' && tools.length > 0 && (
        <details className="tool-trace">
          <summary style={{ cursor: 'pointer' }}>
            {tools.length} data lookup{tools.length > 1 ? 's' : ''} ·{' '}
            {m.meta?.mode === 'llm' ? 'reasoned by the model' : 'answered from the analysis'}
          </summary>
          <div style={{ marginTop: 6 }}>
            {tools.map((t, i) => (
              <div key={i} style={{ marginBottom: 5 }}>
                <code>{t.tool}</code>
                {t.arguments && Object.keys(t.arguments).length > 0 && (
                  <span className="mono"> ({JSON.stringify(t.arguments)})</span>
                )}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

export default function Copilot() {
  const dispatch = useDispatch()
  const { projectId, documentId } = useSelector((s) => s.ui)
  const { data } = useChatHistoryQuery(projectId, { skip: !projectId })
  const [send, { isLoading }] = useSendChatMutation()
  const [clear] = useClearChatMutation()
  const [text, setText] = useState('')
  const [useLlm, setUseLlm] = useState(true)
  const logRef = useRef(null)

  const messages = data?.messages || []

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [messages.length, isLoading])

  const ask = async (q) => {
    const question = (q ?? text).trim()
    if (!question || isLoading) return
    setText('')
    try {
      await send({ projectId, message: question, document_id: documentId, use_llm: useLlm }).unwrap()
    } catch (e) {
      dispatch(toast({ kind: 'error', message: e?.data?.detail || 'The copilot could not answer.' }))
    }
  }

  if (!projectId) return <EmptyState title="No project selected" hint="Pick a project to talk about." />

  return (
    <div className="chat" style={{ height: 'calc(100vh - 56px)' }}>
      <div ref={logRef} className="chat-log">
        {messages.length === 0 && (
          <div style={{ maxWidth: 720, margin: '24px auto', textAlign: 'center' }}>
            <div style={{ fontSize: 30, marginBottom: 8 }}>✦</div>
            <h2 style={{ fontSize: 19, margin: '0 0 6px' }}>Ask about this drawing set</h2>
            <p className="muted small" style={{ maxWidth: 520, margin: '0 auto 20px' }}>
              Every figure comes from the analysis itself — the copilot reads the extracted data
              rather than recalling numbers, and shows you which lookups it made.
            </p>
            <div className="row wrap" style={{ justifyContent: 'center', gap: 8 }}>
              {(data?.suggestions || []).map((s) => (
                <span key={s} className="chip" onClick={() => ask(s)}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <Message key={m.id} m={m} />
        ))}

        {isLoading && (
          <div className="msg assistant">
            <div className="row">
              <div className="spin" /> <span className="muted">Reading the analysis…</span>
            </div>
          </div>
        )}
      </div>

      <div className="chat-input">
        <div className="row">
          <input
            placeholder="e.g. How much 12-inch supply duct is on M-3.1?"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && ask()}
          />
          <button className="primary" disabled={!text.trim() || isLoading} onClick={() => ask()}>
            Ask
          </button>
        </div>
        <div className="row small muted" style={{ marginTop: 8 }}>
          {data?.llm_enabled ? (
            <label className="row" style={{ gap: 6 }}>
              <input
                type="checkbox"
                checked={useLlm}
                onChange={(e) => setUseLlm(e.target.checked)}
                style={{ width: 'auto' }}
              />
              Use the language model for open-ended reasoning
            </label>
          ) : (
            <span>
              Running the rule-based copilot — set <code className="mono">OPENAI_API_KEY</code> to
              enable open-ended reasoning.
            </span>
          )}
          <span className="spacer" />
          {messages.length > 0 && (
            <button className="sm ghost" onClick={() => clear(projectId)}>
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
