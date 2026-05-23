import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { PromptMetrics, RcaProcessingMetrics, Reference, UceContextDebugItem } from '../types';

// ── Context Debug Item ───────────────────────────────────────────────────
const DROP_REASON_LABELS: Record<string, string> = {
  limit_exceeded: 'limit_exceeded',
  below_min_score: 'below_min_score',
  replaced_by_document_context: 'replaced',
};

function ContextDebugItem({ item, variant }: { item: UceContextDebugItem; variant: 'selected' | 'excluded' }) {
  const [rawOpen, setRawOpen] = useState(false);
  const [breakdownOpen, setBreakdownOpen] = useState(false);

  const hasFullContent = !!(item.full_content || item.preview);
  const hasBreakdown = !!(item.score_breakdown && Object.keys(item.score_breakdown).length > 0);
  const hasMatchedTerms = !!(item.matched_terms && item.matched_terms.length > 0);
  const dropLabel = item.drop_reason ? (DROP_REASON_LABELS[item.drop_reason] ?? item.drop_reason) : null;

  return (
    <div className={`context-debug-item context-debug-item--${variant}`}>
      {/* 헤더: source + score */}
      <div className="context-debug-meta">
        <span className="context-debug-source">{item.section || item.source || item.id || '?'}</span>
        <span className="context-debug-score">{item.score != null ? item.score.toFixed(4) : '-'}</span>
      </div>

      {/* taxonomy + drop_reason 태그 */}
      {(item.taxonomy?.length || dropLabel) && (
        <div className="context-debug-tags">
          {item.taxonomy?.map((t) => <span key={t} className="tag-taxonomy">{t}</span>)}
          {dropLabel && <span className="tag-drop">{dropLabel}</span>}
        </div>
      )}

      {/* match reason (선택 항목) */}
      {item.reason && (
        <div className="context-debug-reason">
          <span className="context-debug-reason-label">match: </span>{item.reason}
        </div>
      )}

      {/* drop reason 설명 (제외 항목) */}
      {variant === 'excluded' && item.reason && (
        <div className="context-debug-reason context-debug-reason--drop">
          <span className="context-debug-reason-label">reason: </span>{item.reason}
        </div>
      )}

      {item.score_breakdown && (
        <div className="context-debug-breakdown">
          <span>q: {(item.score_breakdown.normalized_query_tokens || []).join(',') || '-'}</span>
          <span>h: {(item.score_breakdown.normalized_heading_tokens || []).join(',') || '-'}</span>
          <span>overlap: {item.score_breakdown.overlap ?? item.score_breakdown.heading_overlap ?? '-'}</span>
          <span>h_overlap: {item.score_breakdown.heading_overlap ?? '-'}</span>
          <span>level: {item.score_breakdown.heading_level ?? '-'}</span>
          <span>recency: {item.score_breakdown.recency_score ?? '-'}</span>
          <span>heading: {item.score_breakdown.heading_score ?? '-'}</span>
          <span>exact: {item.score_breakdown.exact_match_score ?? '-'}</span>
          <span>threshold: {item.score_breakdown.threshold ?? '-'}</span>
          <span>{item.score_breakdown.heading_match_reason || '-'}</span>
        </div>
      )}

      {/* matched terms */}
      {hasMatchedTerms && (
        <div className="context-debug-matched">
          {item.matched_terms!.map((term) => (
            <span key={term} className="tag-match">{term}</span>
          ))}
        </div>
      )}

      {/* Raw Content 펼치기 */}
      {hasFullContent && (
        <div className="context-debug-expandable">
          <button className="context-expand-btn" onClick={() => setRawOpen(!rawOpen)}>
            {rawOpen ? '▲ Raw 접기' : '▼ Raw 펼치기'}
          </button>
          {rawOpen && (
            <pre className="context-raw-content">{item.full_content || item.preview}</pre>
          )}
        </div>
      )}

      {/* Score Breakdown */}
      {hasBreakdown && (
        <div className="context-debug-expandable">
          <button className="context-expand-btn context-expand-btn--score" onClick={() => setBreakdownOpen(!breakdownOpen)}>
            {breakdownOpen ? '▲ Score 접기' : '▼ Score 분석'}
          </button>
          {breakdownOpen && (
            <table className="score-breakdown-table">
              <tbody>
                {Object.entries(item.score_breakdown!)
                  .sort(([, a], [, b]) => (Number(b) || 0) - (Number(a) || 0))
                  .map(([k, v]) => (
                    <tr key={k}>
                      <th>{k}</th>
                      <td>
                        <div className="score-bar-row">
                          <span className="score-bar" style={{ width: `${Math.min(100, Math.abs(Number(v)) * 100)}%` }} />
                          <span>{typeof v === 'number' ? v.toFixed(4) : String(v)}</span>
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// ── Final Prompt View ───────────────────────────────────────────────────
function FinalPromptView({ prompt }: { prompt: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="final-prompt-section">
      <button className="context-expand-btn context-expand-btn--prompt" onClick={() => setOpen(!open)}>
        {open ? '▲ Final Prompt 접기' : '▼ Final Prompt 보기'}
      </button>
      {open && <pre className="final-prompt-content">{prompt}</pre>}
    </div>
  );
}

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

// ── Shared Context Rendering ─────────────────────────────────────────────
function renderContextItems(
  title: string,
  items: NonNullable<PromptMetrics['survived_items']>,
  emptyText: string,
  variant: 'selected' | 'excluded' = 'selected',
) {
  return (
    <div className="context-debug-section">
      <div className={`context-debug-title context-debug-title--${variant}`}>{title}</div>
      {items.length === 0 ? (
        <div className="context-debug-empty">{emptyText}</div>
      ) : (
        <div className="context-debug-list">
          {items.map((item, index) => (
            <ContextDebugItem key={`${item.id || item.source || title}-${index}`} item={item} variant={variant} />
          ))}
        </div>
      )}
    </div>
  );
}

function ChatDebugPanel({ metrics }: { metrics: PromptMetrics }) {
  const [open, setOpen] = useState(false);

  const compactContextPreview = (text?: string) => {
    const compact = (text || '').replace(/\s+/g, ' ').trim();
    if (!compact) return '-';
    if (compact.length <= 243) return compact;
    return `${compact.slice(0, 160)}...${compact.slice(-80)}`;
  };

  const formatTokensPerSec = () => {
    const tokens = metrics.response_tokens;
    const ms = metrics.llm_total_latency_ms;
    if (!tokens || !ms) return '-';
    return `${((tokens / ms) * 1000).toFixed(1)} tok/s`;
  };

  const rows: [string, string][] = [
    ['모델', metrics.model ?? '-'],
    ['프롬프트 토큰 (입력)', metrics.original_prompt_tokens?.toLocaleString() ?? '-'],
    ['실제 전송 토큰', metrics.final_prompt_tokens?.toLocaleString() ?? '-'],
    ['UCE 사용', metrics.use_uce ? '✅ ON' : '❌ OFF'],
    ['UCE 폴백', metrics.fallback_used ? '⚠️ 네' : '-'],
    ['Query Type', metrics.query_type ?? '-'],
    ['압축 레벨', metrics.compression_level ?? '-'],
    ['검색 컨텍스트 선택', metrics.selected_context_count?.toString() ?? '-'],
    ['검색 컨텍스트 제외', metrics.dropped_context_count?.toString() ?? '-'],
    ['검색 신뢰도', metrics.retrieval_confidence != null ? metrics.retrieval_confidence.toFixed(4) : '-'],
    ['검색 경고', metrics.retrieval_warning ?? '-'],
    ['content_type', metrics.content_type ?? '-'],
    ['UCE 압축률', metrics.compression_ratio != null ? `${(metrics.compression_ratio * 100).toFixed(1)}%` : '-'],
    ['UCE 빌드 시간', metrics.build_context_latency_ms != null ? `${metrics.build_context_latency_ms} ms` : '-'],
    ['첫 토큰 지연', metrics.llm_first_token_ms != null ? `${metrics.llm_first_token_ms} ms` : '-'],
    ['응답 전체 시간', metrics.llm_total_latency_ms != null ? `${(metrics.llm_total_latency_ms / 1000).toFixed(2)} s` : '-'],
    ['응답 토큰 (추정)', metrics.response_tokens?.toLocaleString() ?? '-'],
    ['응답 글자 수', metrics.response_chars?.toLocaleString() ?? '-'],
    ['토큰/초', formatTokensPerSec()],
    ['xDR 데이터셋', metrics.xdr_dataset_id ?? '-'],
    ['xDR 쿼리 의도', metrics.xdr_query_intent ?? '-'],
    ['xDR 쿼리 설명', metrics.xdr_query_description ?? '-'],
    ['xDR SQL', metrics.xdr_query_sql ?? '-'],
    ['xDR 결과 건수', metrics.xdr_query_row_count?.toString() ?? '-'],
  ];

  return (
    <div className="uce-debug-panel chat-debug-panel">
      <button className="uce-debug-toggle chat-debug-toggle" onClick={() => setOpen(!open)}>
        📊 Chat Debug {open ? '접기' : '보기'}
      </button>
      {open && (
        <>
          <table className="uce-debug-table">
            <tbody>
              {rows.map(([key, value]) => (
                <tr key={key}>
                  <th>{key}</th>
                  <td>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {((metrics.survived_items?.length || 0) > 0 || (metrics.dropped_items?.length || 0) > 0) && (
            <div className="context-debug">
              {renderContextItems('선택 컨텍스트', metrics.survived_items || [], '선택된 컨텍스트가 없습니다.', 'selected')}
              {renderContextItems('제외 컨텍스트', metrics.dropped_items || [], '제외된 컨텍스트가 없습니다.', 'excluded')}
            </div>
          )}
          {metrics.final_prompt && <FinalPromptView prompt={metrics.final_prompt} />}
        </>
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

function RcaDebugPanel({ rca, promptMetrics }: { rca: RcaProcessingMetrics; promptMetrics?: PromptMetrics }) {
  const [open, setOpen] = useState(false);
  const stageRows = Object.entries(rca.stage_ms || {});
  const rows = [
    ['원본 xDR 크기', formatBytes(rca.input_xdr_bytes)],
    ['구조화 summary JSON', formatBytes(rca.structured_summary_json_bytes)],
    ['최종 결과 JSON', formatBytes(rca.final_result_json_bytes || rca.result_file_bytes)],
    ['summary / xDR', formatRatio(rca.xdr_to_summary_ratio)],
    ['final JSON / xDR', formatRatio(rca.xdr_to_final_json_ratio)],
    ['summary 축소율', formatRatio(rca.estimated_reduction_ratio)],
    ['최종 축소율', formatRatio(rca.final_reduction_ratio)],
    ['RCA Engine 처리 시간', formatMs(rca.total_engine_ms)],
    ['LLM 첫 토큰', formatMs(rca.llm_first_token_ms)],
    ['LLM 전체 시간', formatMs(rca.llm_total_latency_ms)],
    ['처리 레코드', rca.parsed_records?.toLocaleString() || '-'],
    ['스킵 레코드', rca.skipped_records?.toLocaleString() || '-'],
    ['레코드/초', rca.records_per_second?.toLocaleString() || '-'],
    ['원본 파일 삭제', rca.upload_file_deleted ? '완료' : rca.upload_file_delete_error ? `실패: ${rca.upload_file_delete_error}` : '-'],
  ];

  const uceRows: [string, string][] = promptMetrics?.use_uce ? [
    ['UCE 사용', '✅ ON'],
    ['UCE 폴백', promptMetrics.fallback_used ? '⚠️ 네' : '-'],
    ['원본 토큰 (입력)', promptMetrics.original_prompt_tokens?.toLocaleString() ?? '-'],
    ['최적화 토큰 (출력)', promptMetrics.final_prompt_tokens?.toLocaleString() ?? '-'],
    ['압축률', promptMetrics.compression_ratio != null ? `${(promptMetrics.compression_ratio * 100).toFixed(1)}%` : '-'],
    ['UCE 빌드 시간', promptMetrics.build_context_latency_ms != null ? `${promptMetrics.build_context_latency_ms} ms` : '-'],
    ['선택 섹션', promptMetrics.selected_context_count?.toString() ?? '-'],
    ['제외 섹션', promptMetrics.dropped_context_count?.toString() ?? '-'],
    ['압축 레벨', promptMetrics.compression_level ?? '-'],
    ['검색 신뢰도', promptMetrics.retrieval_confidence != null ? promptMetrics.retrieval_confidence.toFixed(4) : '-'],
    ['검색 경고', promptMetrics.retrieval_warning ?? '-'],
  ] : [];

  const hasUceSections =
    (promptMetrics?.survived_items?.length ?? 0) > 0 ||
    (promptMetrics?.dropped_items?.length ?? 0) > 0;

  return (
    <div className="uce-debug-panel rca-ucedebug-panel">
      <button className="uce-debug-toggle" onClick={() => setOpen(!open)}>
        RCA Debug {open ? '접기' : '보기'}
      </button>
      {open && (
        <>
          <div className="rca-debug-section-label">RCA 처리 지표</div>
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

          {promptMetrics?.use_uce && (
            <>
              <div className="rca-debug-section-label rca-debug-section-label--uce">UCE RCA 최적화</div>
              <table className="uce-debug-table">
                <tbody>
                  {uceRows.map(([key, value]) => (
                    <tr key={key}>
                      <th>{key}</th>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          {hasUceSections && (
            <div className="context-debug">
              {renderContextItems('선택 RCA 섹션', promptMetrics!.survived_items || [], '선택된 섹션이 없습니다.', 'selected')}
              {renderContextItems('제외 RCA 섹션', promptMetrics!.dropped_items || [], '제외된 섹션이 없습니다.', 'excluded')}
            </div>
          )}

          {promptMetrics?.final_prompt && <FinalPromptView prompt={promptMetrics.final_prompt} />}
        </>
      )}
    </div>
  );
}

function RcaInvestigationDebugPanel({ metrics }: { metrics: PromptMetrics }) {
  const [open, setOpen] = useState(false);
  const [sqlOpen, setSqlOpen] = useState(false);
  const [rowsOpen, setRowsOpen] = useState(false);
  const [uceOpen, setUceOpen] = useState(false);
  const [finalPromptOpen, setFinalPromptOpen] = useState(false);

  if (!metrics.xdr_dataset_id) return null;

  const resultRows: Record<string, unknown>[] = metrics.xdr_query_result_rows ?? [];
  const columns = resultRows.length > 0 ? Object.keys(resultRows[0]) : [];

  return (
    <div className="rca-inv-panel">
      <button className="rca-inv-toggle" onClick={() => setOpen(!open)}>
        🔍 RCA 조사 파이프라인 {open ? '접기' : '보기'}
      </button>
      {open && (
        <div className="rca-inv-body">
          {/* 1. Dataset Selection */}
          <div className="rca-inv-section">
            <div className="rca-inv-section-title">1. 데이터셋 선택</div>
            <table className="rca-inv-kv-table">
              <tbody>
                <tr><th>활성 데이터셋</th><td className="rca-inv-mono">{metrics.xdr_dataset_id}</td></tr>
              </tbody>
            </table>
          </div>

          {/* 2. Planner Result */}
          {(metrics.xdr_query_intent || metrics.xdr_query_description) && (
            <div className="rca-inv-section">
              <div className="rca-inv-section-title">2. 쿼리 플래너 결과</div>
              <table className="rca-inv-kv-table">
                <tbody>
                  {metrics.xdr_query_intent && (
                    <tr><th>의도 (intent)</th><td>{metrics.xdr_query_intent}</td></tr>
                  )}
                  {metrics.xdr_query_description && (
                    <tr><th>설명</th><td>{metrics.xdr_query_description}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* 3. Generated SQL */}
          {metrics.xdr_query_sql && (
            <div className="rca-inv-section">
              <div className="rca-inv-section-title">3. 생성된 SQL</div>
              <button className="rca-inv-expand-btn" onClick={() => setSqlOpen(!sqlOpen)}>
                {sqlOpen ? '▲ SQL 접기' : '▼ SQL 보기'}
              </button>
              {sqlOpen && <pre className="rca-inv-sql">{metrics.xdr_query_sql}</pre>}
            </div>
          )}

          {/* 4. Execution Metadata */}
          <div className="rca-inv-section">
            <div className="rca-inv-section-title">4. 쿼리 실행 메타데이터</div>
            <table className="rca-inv-kv-table">
              <tbody>
                <tr>
                  <th>실행 시간</th>
                  <td>{metrics.xdr_query_execution_ms != null ? `${metrics.xdr_query_execution_ms} ms` : '-'}</td>
                </tr>
                <tr>
                  <th>결과 건수</th>
                  <td>{metrics.xdr_query_row_count?.toLocaleString() ?? '-'}건</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 5. Raw Query Result */}
          <div className="rca-inv-section">
            <div className="rca-inv-section-title">5. 원시 쿼리 결과</div>
            {resultRows.length === 0 ? (
              <div className="rca-inv-empty">결과 없음</div>
            ) : (
              <>
                <button className="rca-inv-expand-btn" onClick={() => setRowsOpen(!rowsOpen)}>
                  {rowsOpen ? '▲ 결과 접기' : `▼ 결과 보기 (${resultRows.length}건)`}
                </button>
                {rowsOpen && (
                  <div className="rca-inv-table-scroll">
                    <table className="rca-inv-result-table">
                      <thead>
                        <tr>{columns.map((col) => <th key={col}>{col}</th>)}</tr>
                      </thead>
                      <tbody>
                        {resultRows.map((row, i) => (
                          <tr key={i}>
                            {columns.map((col) => (
                              <td key={col}>{row[col] != null ? String(row[col]) : '-'}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>

          {/* 6. UCE Compression */}
          {metrics.use_uce && (
            <div className="rca-inv-section">
              <div className="rca-inv-section-title">6. UCE 압축 현황</div>
              <button className="rca-inv-expand-btn" onClick={() => setUceOpen(!uceOpen)}>
                {uceOpen ? '▲ UCE 접기' : '▼ UCE 압축 상세 보기'}
              </button>
              {uceOpen && (
                <>
                  <table className="rca-inv-kv-table">
                    <tbody>
                      <tr>
                        <th>압축률</th>
                        <td>{metrics.compression_ratio != null ? `${(metrics.compression_ratio * 100).toFixed(1)}%` : '-'}</td>
                      </tr>
                      <tr><th>선택 섹션</th><td>{metrics.selected_context_count?.toString() ?? '-'}</td></tr>
                      <tr><th>제외 섹션</th><td>{metrics.dropped_context_count?.toString() ?? '-'}</td></tr>
                      <tr>
                        <th>UCE 빌드 시간</th>
                        <td>{metrics.build_context_latency_ms != null ? `${metrics.build_context_latency_ms} ms` : '-'}</td>
                      </tr>
                    </tbody>
                  </table>
                  {((metrics.survived_items?.length || 0) > 0 || (metrics.dropped_items?.length || 0) > 0) && (
                    <div className="context-debug">
                      {renderContextItems('선택 컨텍스트', metrics.survived_items || [], '선택된 컨텍스트가 없습니다.', 'selected')}
                      {renderContextItems('제외 컨텍스트', metrics.dropped_items || [], '제외된 컨텍스트가 없습니다.', 'excluded')}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* 7. Final Context */}
          {metrics.final_prompt && (
            <div className="rca-inv-section">
              <div className="rca-inv-section-title">7. 최종 컨텍스트 (LLM 입력)</div>
              <button className="rca-inv-expand-btn" onClick={() => setFinalPromptOpen(!finalPromptOpen)}>
                {finalPromptOpen ? '▲ 접기' : '▼ Final Prompt 보기'}
              </button>
              {finalPromptOpen && <pre className="final-prompt-content">{metrics.final_prompt}</pre>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChatMessage({ role, content, references, metrics }: Props) {
  const debugEnabled = process.env.REACT_APP_UCE_DEBUG === 'true';
  const rcaDebugEnabled = process.env.REACT_APP_RCA_DEBUG === 'true';
  const chatDebugEnabled = process.env.REACT_APP_CHAT_DEBUG === 'true';
  const [expanded, setExpanded] = useState(false);
  const COLLAPSE_THRESHOLD = 400; // px
  const isLong = role === 'user' && content.length > 300;

  return (
    <div className={`message ${role}`}>
      <div className="message-avatar">
        {role === 'user'
          ? <img src="/send_icon.svg" alt="User" className="avatar-icon" />
          : <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />}
      </div>
      <div className="message-content">
        <div
          className={`message-body${role === 'assistant' ? ' markdown-body' : ''}${isLong && !expanded ? ' message-collapsed' : ''}`}
        >
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
        </div>
        {isLong && (
          <button className="expand-btn" onClick={() => setExpanded(!expanded)}>
            {expanded ? '▲ 접기' : '▼ 더 보기'}
          </button>
        )}
        {references && references.length > 0 && (
          <div className="references">
            <span className="references-label">참조 문서</span>
            {references.map((ref, idx) => (
              <span key={idx} className="reference-chip">
                {ref.filename}
                {ref.type !== 'rca' && (
                  <span className="reference-score">{Math.round(ref.score * 100)}%</span>
                )}
              </span>
            ))}
          </div>
        )}
        {debugEnabled && role === 'assistant' && metrics && !metrics.rca_processing && <UceDebugPanel metrics={metrics} />}
        {chatDebugEnabled && role === 'assistant' && metrics && !metrics.rca_processing && <ChatDebugPanel metrics={metrics} />}
        {chatDebugEnabled && role === 'assistant' && metrics?.xdr_dataset_id && <RcaInvestigationDebugPanel metrics={metrics} />}
        {rcaDebugEnabled && role === 'assistant' && metrics?.rca_processing && (
          <RcaDebugPanel rca={metrics.rca_processing} promptMetrics={metrics} />
        )}
      </div>
    </div>
  );
}
