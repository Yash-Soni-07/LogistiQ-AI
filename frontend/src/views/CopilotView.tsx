import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Bot, User, ChevronRight, ChevronDown, Terminal, Activity,
  Zap, Server, MessageSquare, Plus, ExternalLink, AlertTriangle, Loader2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuthStore } from '@/stores/auth.store';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ActionCard {
  id: string;
  title: string;
  icon: React.ReactNode;
  prompt: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string[];
  actions?: ActionCard[];
  isStreaming?: boolean;
  sources?: string[];
  intent?: string;
}

// ---------------------------------------------------------------------------
// Static data
// ---------------------------------------------------------------------------

const MCP_SERVERS = [
  { name: 'logistiq-core-db',   status: 'online',   latency: 12  },
  { name: 'gdelt-event-stream', status: 'online',   latency: 45  },
  { name: 'vrp-solver-engine',  status: 'online',   latency: 110 },
  { name: 'weather-api-bridge', status: 'degraded', latency: 450 },
] as const;

const ACTIVE_AGENTS = [
  { name: 'Sentinel Analyst', task: 'Monitoring SE Asia ports'   },
  { name: 'Decision Engine',  task: 'Processing disruption events' },
] as const;

const SUGGESTED_QUERIES = [
  'How many shipments are delayed right now?',
  'What is the flood risk near Mumbai?',
  'Best route from Pune to Kolkata?',
  'Show me shipment status summary',
];

// ---------------------------------------------------------------------------
// WebSocket Copilot Stream — connects to /ws/copilot/{sessionId}
// ---------------------------------------------------------------------------

function buildCopilotWsUrl(sessionId: string, token: string): string {
  const rawBase = (import.meta.env.VITE_WS_URL as string | undefined)?.trim() || 'ws://localhost:8000';
  let parsedBase: URL;
  try { parsedBase = new URL(rawBase); } catch { parsedBase = new URL(`ws://${rawBase}`); }
  const protocol = parsedBase.protocol === 'https:' ? 'wss:' : parsedBase.protocol === 'http:' ? 'ws:' : parsedBase.protocol;
  return `${protocol}//${parsedBase.host}/ws/copilot/${sessionId}?token=${encodeURIComponent(token)}`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1 h-5 px-1">
      <span className="w-1.5 h-1.5 bg-[var(--lq-text-dim)] rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
      <span className="w-1.5 h-1.5 bg-[var(--lq-text-dim)] rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
      <span className="w-1.5 h-1.5 bg-[var(--lq-text-dim)] rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CopilotView() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'm1',
      role: 'assistant',
      content:
        'LogistiQ Copilot initialized. I have full context of your active shipments, risk data, and routing intelligence. Ask me anything about your logistics operations.',
      actions: [
        { id: 'a1', title: 'Audit High Risk', icon: <AlertTriangle size={14} />, prompt: 'Show me all shipments with a risk score above 0.7.' },
        { id: 'a2', title: 'Check Delays', icon: <Activity size={14} />, prompt: 'How many shipments are delayed right now?' },
      ],
    },
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [expandedReasoning, setExpandedReasoning] = useState<Record<string, boolean>>({});
  const [tokenCount, setTokenCount] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const activeWsRef = useRef<WebSocket | null>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Cleanup active WS on unmount
  useEffect(() => () => {
    if (activeWsRef.current && activeWsRef.current.readyState <= 1) {
      activeWsRef.current.close();
    }
  }, []);

  const toggleReasoning = (id: string) =>
    setExpandedReasoning((prev) => ({ ...prev, [id]: !prev[id] }));

  const handleSend = useCallback((text: string) => {
    if (!text.trim() || isTyping) return;

    const token = useAuthStore.getState().token;
    if (!token) return;

    const userMsg: Message = { id: `u-${Date.now()}`, role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    const aiMsgId = `a-${Date.now()}`;
    const sessionId = `s-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

    // Create streaming AI message placeholder
    const streamingMsg: Message = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
    };
    setMessages(prev => [...prev, streamingMsg]);

    // Connect to copilot WebSocket
    const wsUrl = buildCopilotWsUrl(sessionId, token);
    const ws = new WebSocket(wsUrl);
    activeWsRef.current = ws;

    let fullContent = '';
    let reasoningSteps: string[] = [];
    let suggestedActions: ActionCard[] = [];
    let sources: string[] = [];
    let intent = '';

    ws.onopen = () => {
      // Send the user's question as the first message
      ws.send(text);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'token') {
          fullContent += data.content;
          setMessages(prev =>
            prev.map(m => m.id === aiMsgId ? { ...m, content: fullContent } : m)
          );
          setTokenCount(c => c + (data.content?.length || 0));
        } else if (data.type === 'done') {
          reasoningSteps = data.reasoning_steps || [];
          sources = data.sources || [];
          intent = data.intent || '';

          // Build action cards from suggested_actions
          if (data.suggested_actions && Array.isArray(data.suggested_actions)) {
            suggestedActions = data.suggested_actions.slice(0, 3).map((act: any, i: number) => ({
              id: `act-${Date.now()}-${i}`,
              title: act.tool || act.title || `Action ${i + 1}`,
              icon: <Zap size={14} />,
              prompt: act.prompt || `Execute ${act.tool || 'action'}`,
            }));
          }

          setMessages(prev =>
            prev.map(m =>
              m.id === aiMsgId
                ? {
                    ...m,
                    content: fullContent || 'I processed your request.',
                    isStreaming: false,
                    reasoning: reasoningSteps.length > 0 ? reasoningSteps : undefined,
                    actions: suggestedActions.length > 0 ? suggestedActions : undefined,
                    sources,
                    intent,
                  }
                : m
            )
          );
          setIsTyping(false);
          ws.close();
        }
      } catch {
        // Non-JSON message
        fullContent += event.data;
        setMessages(prev =>
          prev.map(m => m.id === aiMsgId ? { ...m, content: fullContent } : m)
        );
      }
    };

    ws.onerror = () => {
      setMessages(prev =>
        prev.map(m =>
          m.id === aiMsgId
            ? { ...m, content: fullContent || 'Connection error. Please try again.', isStreaming: false }
            : m
        )
      );
      setIsTyping(false);
    };

    ws.onclose = () => {
      // Finalize if not already done
      setMessages(prev =>
        prev.map(m =>
          m.id === aiMsgId && m.isStreaming
            ? { ...m, content: fullContent || 'Response ended.', isStreaming: false }
            : m
        )
      );
      setIsTyping(false);
      activeWsRef.current = null;
    };
  }, [isTyping]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-1 min-h-0 bg-[var(--lq-bg)] overflow-hidden">

      {/* ── Chat area ──────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0">

        {/* Header */}
        <div className="h-14 shrink-0 border-b border-[var(--lq-border)] bg-[var(--lq-surface)] flex items-center px-6 gap-3">
          <Bot className="text-[var(--lq-cyan)]" size={20} />
          <h2 className="text-sm font-semibold text-[var(--lq-text-bright)] tracking-wide">LogistiQ Copilot</h2>
          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20 uppercase">
            Gemini · Live
          </span>
          {isTyping && (
            <span className="ml-auto text-[10px] text-[var(--lq-text-dim)] animate-pulse font-mono">Thinking...</span>
          )}
        </div>

        {/* Messages feed — scrollable with styled scrollbar */}
        <div
          ref={chatContainerRef}
          className="flex-1 overflow-y-auto p-6 space-y-6"
          style={{
            scrollbarWidth: 'thin',
            scrollbarColor: 'var(--lq-border) transparent',
          }}
        >
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn('flex gap-4 max-w-3xl', msg.role === 'user' ? 'ml-auto' : '')}
            >
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded shrink-0 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] flex items-center justify-center text-[var(--lq-cyan)]">
                  <Bot size={18} />
                </div>
              )}

              <div className={cn('flex flex-col gap-2 min-w-0', msg.role === 'user' ? 'items-end' : 'items-start')}>

                {/* Reasoning trace */}
                {msg.reasoning && msg.reasoning.length > 0 && (
                  <div className="w-full max-w-xl">
                    <button
                      onClick={() => toggleReasoning(msg.id)}
                      className="flex items-center gap-1.5 text-xs text-[var(--lq-text-dim)] hover:text-[var(--lq-text-bright)] transition-colors mb-1 font-mono"
                    >
                      {expandedReasoning[msg.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      Reasoning Trace ({msg.reasoning.length} steps)
                    </button>
                    {expandedReasoning[msg.id] && (
                      <div className="bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded-md p-3 mb-2 space-y-1.5">
                        {msg.reasoning.map((step, i) => (
                          <div key={i} className="flex items-start gap-2 text-xs font-mono text-[var(--lq-text)]">
                            <span className="text-[var(--lq-text-dim)] shrink-0">[{i + 1}]</span>
                            <span>{step}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Bubble */}
                <div
                  className={cn(
                    'px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap max-w-xl',
                    msg.role === 'user'
                      ? 'bg-[var(--lq-cyan)] text-white rounded-tr-sm'
                      : 'bg-slate-100 dark:bg-[var(--lq-surface)] border border-[var(--lq-border)] text-[var(--lq-text-bright)] rounded-tl-sm shadow-sm',
                  )}
                >
                  {msg.content}
                  {msg.isStreaming && (
                    <span className="ml-1 inline-block w-1.5 h-4 bg-[var(--lq-cyan)] animate-pulse align-middle" />
                  )}
                </div>

                {/* Sources */}
                {msg.sources && msg.sources.length > 0 && !msg.isStreaming && (
                  <div className="flex items-center gap-1.5 text-[9px] text-[var(--lq-text-dim)] font-mono">
                    <span>Sources:</span>
                    {msg.sources.map((s, i) => (
                      <span key={i} className="px-1.5 py-0.5 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] rounded">{s}</span>
                    ))}
                  </div>
                )}

                {/* Action cards */}
                {msg.actions && msg.actions.length > 0 && !msg.isStreaming && (
                  <div className="flex flex-wrap gap-2 mt-1">
                    {msg.actions.map((action) => (
                      <button
                        key={action.id}
                        onClick={() => handleSend(action.prompt)}
                        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--lq-border)] bg-[var(--lq-surface)] hover:bg-[var(--lq-surface-2)] hover:border-cyan-500/50 transition-colors text-xs text-[var(--lq-text-bright)] group"
                      >
                        <span className="text-[var(--lq-cyan)]">{action.icon}</span>
                        {action.title}
                        <ExternalLink size={12} className="text-[var(--lq-text-dim)] group-hover:text-[var(--lq-cyan)] transition-colors ml-1" />
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded shrink-0 bg-[var(--lq-surface)] border border-[var(--lq-border)] flex items-center justify-center text-[var(--lq-text-dim)]">
                  <User size={18} />
                </div>
              )}
            </div>
          ))}

          {isTyping && (
            <div className="flex gap-4 max-w-3xl">
              <div className="w-8 h-8 rounded shrink-0 bg-[var(--lq-surface-2)] border border-[var(--lq-border)] flex items-center justify-center text-[var(--lq-cyan)]">
                <Bot size={18} />
              </div>
              <div className="px-4 py-3 rounded-2xl bg-[var(--lq-surface)] border border-[var(--lq-border)] rounded-tl-sm shadow-sm flex items-center">
                <TypingIndicator />
              </div>
            </div>
          )}

          <div ref={messagesEndRef} className="h-4" />
        </div>

        {/* Input */}
        <div className="p-4 bg-[var(--lq-surface)] border-t border-[var(--lq-border)] shrink-0">
          {/* Suggested chips */}
          <div className="flex flex-nowrap overflow-x-auto gap-2 pb-3" style={{ scrollbarWidth: 'none' }}>
            {SUGGESTED_QUERIES.map((q, i) => (
              <button
                key={i}
                onClick={() => setInput(q)}
                className="shrink-0 px-3 py-1.5 rounded-full border border-[var(--lq-border-hover)] bg-[var(--lq-bg)] hover:bg-[var(--lq-surface-2)] text-xs text-[var(--lq-text)] font-medium transition-colors whitespace-nowrap"
              >
                {q}
              </button>
            ))}
          </div>

          <div className="relative">
            <div className="absolute left-3 top-3 text-[var(--lq-text-dim)]">
              <Plus size={20} />
            </div>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(input);
                }
              }}
              placeholder="Ask Copilot anything… (Enter to send, Shift+Enter for new line)"
              className="w-full bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded-xl py-3 pl-10 pr-14 text-sm text-[var(--lq-text-bright)] placeholder:text-[var(--lq-text-dim)] focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30 resize-none transition-colors"
              rows={1}
              style={{ minHeight: '48px', maxHeight: '120px' }}
            />
            <button
              onClick={() => handleSend(input)}
              disabled={!input.trim() || isTyping}
              className="absolute right-2 top-2 p-2 rounded-lg bg-[var(--lq-cyan)] text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity shadow-sm"
            >
              {isTyping ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
        </div>
      </div>

      {/* ── Context sidebar (280px) ────────────────────────────────── */}
      <div className="w-[280px] shrink-0 border-l border-[var(--lq-border)] bg-[var(--lq-surface-2)] flex flex-col min-h-0">
        <div className="h-14 border-b border-[var(--lq-border)] flex items-center px-4 shrink-0">
          <Terminal className="text-[var(--lq-text-dim)] mr-2" size={16} />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--lq-text-bright)]">System Context</h3>
        </div>

        <div className="p-4 space-y-6 overflow-y-auto flex-1" style={{ scrollbarWidth: 'thin', scrollbarColor: 'var(--lq-border) transparent' }}>

          {/* MCP Servers */}
          <div>
            <h4 className="text-[10px] font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-3">MCP Servers</h4>
            <div className="space-y-2">
              {MCP_SERVERS.map((server) => (
                <div key={server.name} className="flex items-center justify-between bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded p-2">
                  <div className="flex items-center gap-2">
                    <div className={cn('w-2 h-2 rounded-full', server.status === 'online' ? 'bg-[var(--lq-green)]' : 'bg-[var(--lq-amber)]')} />
                    <span className="text-xs font-mono text-[var(--lq-text-bright)] truncate max-w-[120px]">{server.name}</span>
                  </div>
                  <span className={cn('text-[10px] font-mono', server.latency > 200 ? 'text-[var(--lq-amber)]' : 'text-[var(--lq-text-dim)]')}>
                    {server.latency}ms
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Active Agents */}
          <div>
            <h4 className="text-[10px] font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-3">Active Agents</h4>
            <div className="space-y-2">
              {ACTIVE_AGENTS.map((agent, i) => (
                <div key={i} className="bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded p-2 border-l-2 border-l-[var(--lq-cyan)]">
                  <div className="flex items-center gap-1.5 mb-1">
                    <Server size={12} className="text-[var(--lq-text-dim)]" />
                    <span className="text-xs font-semibold text-[var(--lq-text-bright)]">{agent.name}</span>
                  </div>
                  <p className="text-[10px] text-[var(--lq-text-dim)] ml-4">{agent.task}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Session Stats */}
          <div>
            <h4 className="text-[10px] font-semibold text-[var(--lq-text-bright)] uppercase tracking-wider mb-3">Session Stats</h4>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded p-2 flex flex-col gap-1">
                <MessageSquare size={14} className="text-[var(--lq-text-dim)]" />
                <span className="text-sm font-mono font-bold text-[var(--lq-text-bright)]">
                  {messages.filter((m) => m.role === 'user').length}
                </span>
                <span className="text-[9px] text-[var(--lq-text-dim)] uppercase">Queries</span>
              </div>
              <div className="bg-[var(--lq-bg)] border border-[var(--lq-border)] rounded p-2 flex flex-col gap-1">
                <Zap size={14} className="text-[var(--lq-amber)]" />
                <span className="text-sm font-mono font-bold text-[var(--lq-text-bright)]">{tokenCount.toLocaleString()}</span>
                <span className="text-[9px] text-[var(--lq-text-dim)] uppercase">Chars Streamed</span>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
