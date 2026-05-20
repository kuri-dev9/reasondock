import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { PromptMetrics, Reference } from '../types';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  references?: Reference[];
  metrics?: PromptMetrics | null;
}

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-language">{language}</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? '복사됨' : '복사'}
        </button>
      </div>
      <SyntaxHighlighter style={oneDark} language={language} PreTag="div">
        {children}
      </SyntaxHighlighter>
    </div>
  );
}

function UceDebugPanel({ metrics }: { metrics: PromptMetrics }) {
  const [open, setOpen] = useState(false);
  const rows = [
    ['use_uce', metrics.use_uce],
    ['fallback_used', metrics.fallback_used],
    ['original_prompt_tokens', metrics.original_prompt_tokens],
    ['final_prompt_tokens', metrics.final_prompt_tokens],
    ['compression_ratio', metrics.compression_ratio],
    ['build_context_latency_ms', metrics.build_context_latency_ms],
    ['llm_first_token_ms', metrics.llm_first_token_ms],
    ['llm_total_latency_ms', metrics.llm_total_latency_ms],
    ['selected_context_count', metrics.selected_context_count],
    ['dropped_context_count', metrics.dropped_context_count],
    ['intent', metrics.intent],
    ['topic_relation', metrics.topic_relation],
  ];
  return (
    <div className="uce-debug-panel">
      <button className="uce-debug-toggle" onClick={() => setOpen(!open)}>
        UCE Debug {open ? '접기' : '보기'}
      </button>
      {open && (
        <table className="uce-debug-table">
          <tbody>
            {rows.map(([key, value]) => (
              <tr key={String(key)}>
                <th>{key}</th>
                <td>{value === null || value === undefined ? '-' : String(value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function ChatMessage({ role, content, references, metrics }: Props) {
  const debugEnabled = process.env.REACT_APP_UCE_DEBUG === 'true';
  return (
    <div className={`message ${role}`}>
      <div className="message-avatar">
        {role === 'user'
          ? <img src="/send_icon.svg" alt="User" className="avatar-icon" />
          : <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />}
      </div>
      <div className="message-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ node, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              const inline = !match && !String(children).includes('\n');
              if (inline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              return (
                <CodeBlock language={match ? match[1] : 'text'}>
                  {String(children).replace(/\n$/, '')}
                </CodeBlock>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
        {references && references.length > 0 && (
          <div className="references">
            <span className="references-label">참조 문서</span>
            {references.map((ref, idx) => (
              <span key={idx} className="reference-chip">
                {ref.filename}
                <span className="reference-score">{Math.round(ref.score * 100)}%</span>
              </span>
            ))}
          </div>
        )}
        {debugEnabled && role === 'assistant' && metrics && <UceDebugPanel metrics={metrics} />}
      </div>
    </div>
  );
}
