import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { PromptMetrics, RcaProcessingMetrics, Reference } from '../types';

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

function formatBytes(value?: number | null) {
  if (value === null || value === undefined) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 2)} ${units[unit]}`;
}

function formatMs(value?: number | null) {
  if (value === null || value === undefined) return '-';
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function formatRatio(value?: number | null) {
  if (value === null || value === undefined) return '-';
  return `${(value * 100).toFixed(2)}%`;
}

function RcaDebugPanel({ metrics }: { metrics: RcaProcessingMetrics }) {
  const [open, setOpen] = useState(false);
  const stageRows = Object.entries(metrics.stage_ms || {});
  const rows = [
    ['원본 xDR 크기', formatBytes(metrics.input_xdr_bytes)],
    ['구조화 summary JSON', formatBytes(metrics.structured_summary_json_bytes)],
    ['최종 결과 JSON', formatBytes(metrics.final_result_json_bytes || metrics.result_file_bytes)],
    ['summary / xDR', formatRatio(metrics.xdr_to_summary_ratio)],
    ['final JSON / xDR', formatRatio(metrics.xdr_to_final_json_ratio)],
    ['summary 축소율', formatRatio(metrics.estimated_reduction_ratio)],
    ['최종 축소율', formatRatio(metrics.final_reduction_ratio)],
    ['RCA Engine 처리 시간', formatMs(metrics.total_engine_ms)],
    ['LLM 첫 토큰', formatMs(metrics.llm_first_token_ms)],
    ['LLM 전체 시간', formatMs(metrics.llm_total_latency_ms)],
    ['처리 레코드', metrics.parsed_records?.toLocaleString() || '-'],
    ['스킵 레코드', metrics.skipped_records?.toLocaleString() || '-'],
    ['레코드/초', metrics.records_per_second?.toLocaleString() || '-'],
    ['원본 파일 삭제', metrics.upload_file_deleted ? '완료' : metrics.upload_file_delete_error ? `실패: ${metrics.upload_file_delete_error}` : '-'],
  ];
  return (
    <div className="uce-debug-panel">
      <button className="uce-debug-toggle" onClick={() => setOpen(!open)}>
        RCA Processing {open ? '접기' : '보기'}
      </button>
      {open && (
        <>
          <table className="uce-debug-table">
            <tbody>
              {rows.map(([key, value]) => (
                <tr key={String(key)}>
                  <th>{key}</th>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {stageRows.length > 0 && (
            <table className="uce-debug-table rca-stage-table">
              <tbody>
                {stageRows.map(([key, value]) => (
                  <tr key={key}>
                    <th>{key}</th>
                    <td>{formatMs(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

export default function ChatMessage({ role, content, references, metrics }: Props) {
  const debugEnabled = process.env.REACT_APP_UCE_DEBUG === 'true';
  const rcaDebugEnabled = process.env.REACT_APP_RCA_DEBUG === 'true';
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
        {rcaDebugEnabled && role === 'assistant' && metrics?.rca_processing && (
          <RcaDebugPanel metrics={metrics.rca_processing} />
        )}
      </div>
    </div>
  );
}
