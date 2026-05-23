import React, { useState, useEffect, useCallback } from 'react';
import { ConversationDataset, RcaDataset } from '../types';
import {
  fetchRcaDatasets,
  fetchConversationDatasets,
  attachDataset,
  detachDataset,
  setPrimaryDataset,
  deleteRcaDataset,
  fetchRcaDatasetSummary,
} from '../api';

interface Props {
  visible: boolean;
  onClose: () => void;
  conversationId?: number | null;
  selectedDatasetId?: string | null;
  onSelectDataset?: (datasetId: string | null) => void;
}

type Tab = 'conversation' | 'global';

export default function RcaDatasetPanel({ visible, onClose, conversationId, selectedDatasetId, onSelectDataset }: Props) {
  const [tab, setTab] = useState<Tab>(conversationId ? 'conversation' : 'global');
  const [allDatasets, setAllDatasets] = useState<RcaDataset[]>([]);
  const [convDatasets, setConvDatasets] = useState<ConversationDataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, any>>({});
  const [actingOn, setActingOn] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [all, conv] = await Promise.all([
        fetchRcaDatasets(),
        conversationId ? fetchConversationDatasets(conversationId) : Promise.resolve([]),
      ]);
      setAllDatasets(all);
      setConvDatasets(conv);
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    if (visible) {
      setTab(conversationId ? 'conversation' : 'global');
      loadAll();
    }
  }, [visible, loadAll]);

  const handleExpand = async (datasetId: string) => {
    if (expandedId === datasetId) { setExpandedId(null); return; }
    setExpandedId(datasetId);
    if (!summaries[datasetId]) {
      try {
        const s = await fetchRcaDatasetSummary(datasetId);
        setSummaries((p) => ({ ...p, [datasetId]: s }));
      } catch {}
    }
  };

  const handleAttach = async (datasetId: string) => {
    if (!conversationId) return;
    setActingOn(datasetId);
    try {
      await attachDataset(conversationId, datasetId);
      await loadAll();
    } catch (err: any) {
      alert(err.message || '첨부 실패');
    } finally { setActingOn(null); }
  };

  const handleDetach = async (datasetId: string) => {
    if (!conversationId) return;
    if (!window.confirm(`"${datasetId}" 를 이 대화에서 분리하시겠습니까?\n데이터셋 자체는 삭제되지 않습니다.`)) return;
    setActingOn(datasetId);
    try {
      await detachDataset(conversationId, datasetId);
      await loadAll();
    } catch (err: any) {
      alert(err.message || '분리 실패');
    } finally { setActingOn(null); }
  };

  const handleSetPrimary = async (datasetId: string) => {
    if (!conversationId) return;
    setActingOn(datasetId);
    try {
      await setPrimaryDataset(conversationId, datasetId);
      await loadAll();
    } catch (err: any) {
      alert(err.message || '주 데이터셋 설정 실패');
    } finally { setActingOn(null); }
  };

  const handleDelete = async (datasetId: string) => {
    if (!window.confirm(`데이터셋 "${datasetId}"을(를) 영구 삭제하시겠습니까?\nDuckDB 레코드와 모든 대화 첨부가 삭제됩니다.`)) return;
    setActingOn(datasetId);
    try {
      await deleteRcaDataset(datasetId);
      await loadAll();
      if (expandedId === datasetId) setExpandedId(null);
    } catch (err: any) {
      alert(err.message || '삭제 실패');
    } finally { setActingOn(null); }
  };

  const attachedIds = new Set(convDatasets.map((d) => d.dataset_id));

  const formatPeriod = (startUs?: number | null, endUs?: number | null) => {
    if (!startUs) return '-';
    const s = new Date(startUs / 1000).toISOString().replace('T', ' ').slice(0, 19);
    const e = endUs ? new Date(endUs / 1000).toISOString().replace('T', ' ').slice(0, 19) : '-';
    return `${s} ~ ${e}`;
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return '-';
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const statusBadge = (status: string) => {
    const cls = status === 'READY' ? 'ready' : status === 'PROCESSING' ? 'processing' : 'error';
    const label = status === 'READY' ? 'READY' : status === 'PROCESSING' ? '처리중' : '오류';
    return <span className={`rca-ds-badge ${cls}`}>{label}</span>;
  };

  const renderSummaryBody = (datasetId: string, summary: any) => {
    if (!summary) return <div className="rca-ds-summary-loading">로딩 중...</div>;
    const overall = summary.overall || {};
    const topFailures = summary.top_failures || [];
    return (
      <div className="rca-ds-summary">
        <div className="rca-ds-summary-row"><span>총 레코드</span><span>{overall.total?.toLocaleString() ?? '-'}</span></div>
        <div className="rca-ds-summary-row">
          <span>시도 / 성공 / 실패</span>
          <span>{overall.attempt?.toLocaleString() ?? '-'} /&nbsp;{overall.success?.toLocaleString() ?? '-'} /&nbsp;{overall.fail?.toLocaleString() ?? '-'}</span>
        </div>
        <div className="rca-ds-summary-row">
          <span>실패율</span>
          <span className={overall.fail_rate > 0.1 ? 'rca-warn' : ''}>
            {overall.fail_rate != null ? `${(overall.fail_rate * 100).toFixed(2)}%` : '-'}
          </span>
        </div>
        {topFailures.length > 0 && (
          <>
            <div className="rca-ds-summary-label">주요 실패 패턴</div>
            {topFailures.slice(0, 3).map((f: any, i: number) => (
              <div key={i} className="rca-ds-summary-row failure">
                <span className="rca-ds-failure-key">{f.key?.split('|').slice(0, 2).join(' › ')}</span>
                <span>{f.count?.toLocaleString()}건</span>
              </div>
            ))}
          </>
        )}
      </div>
    );
  };

  const renderDatasetRow = (ds: RcaDataset, opts: { isPrimary?: boolean; showAttachActions?: boolean }) => {
    const acting = actingOn === ds.dataset_id;
    const isAttached = attachedIds.has(ds.dataset_id);
    const isSelected = selectedDatasetId === ds.dataset_id;
    return (
      <div key={ds.dataset_id} className={`knowledge-item-wrapper${isSelected ? ' rca-ds-active' : ''}`}>
        <div className="knowledge-item">
          <label className="rca-ds-select" title={isSelected ? '선택 해제' : '이 데이터셋 활성화'}>
            <input
              type="checkbox"
              className="rca-ds-checkbox"
              checked={isSelected}
              onChange={() => onSelectDataset?.(isSelected ? null : ds.dataset_id)}
              onClick={(e) => e.stopPropagation()}
            />
          </label>
          <div className="knowledge-item-info" onClick={() => handleExpand(ds.dataset_id)} style={{ cursor: 'pointer' }}>
            <span className="knowledge-item-name">
              <span className="knowledge-expand-icon">{expandedId === ds.dataset_id ? '▾' : '▸'}</span>
              {opts.isPrimary && <span className="rca-ds-primary-badge">주</span>}
              {ds.filename || ds.dataset_id}
            </span>
            <span className="knowledge-item-meta">
              {ds.record_count?.toLocaleString() ?? '-'}건
              {ds.file_size ? ` · ${formatSize(ds.file_size)}` : ''}
              {ds.schema_name ? ` · ${ds.schema_name}` : ''}
              {' · '}{statusBadge(ds.status)}
            </span>
          </div>
          <div className="rca-ds-actions">
            {opts.showAttachActions && conversationId && (
              isAttached ? (
                <>
                  {!opts.isPrimary && (
                    <button className="rca-ds-btn" onClick={() => handleSetPrimary(ds.dataset_id)} disabled={acting}>주로 설정</button>
                  )}
                  <button className="rca-ds-btn detach" onClick={() => handleDetach(ds.dataset_id)} disabled={acting}>분리</button>
                </>
              ) : (
                <button className="rca-ds-btn attach" onClick={() => handleAttach(ds.dataset_id)} disabled={acting}>첨부</button>
              )
            )}
            <button className="knowledge-item-delete" onClick={() => handleDelete(ds.dataset_id)} disabled={acting}>삭제</button>
          </div>
        </div>
        {expandedId === ds.dataset_id && (
          <div className="knowledge-summary">
            <div className="rca-ds-period">📅 {formatPeriod(ds.period_start, ds.period_end)}</div>
            {renderSummaryBody(ds.dataset_id, summaries[ds.dataset_id])}
          </div>
        )}
      </div>
    );
  };

  if (!visible) return null;

  return (
    <div className="knowledge-overlay" onClick={onClose}>
      <div className="knowledge-panel" onClick={(e) => e.stopPropagation()}>
        <div className="knowledge-header">
          <h3>🔍 RCA 데이터셋</h3>
          <button className="knowledge-close" onClick={onClose}>×</button>
        </div>

        {conversationId && (
          <div className="rca-ds-tabs">
            <button className={`rca-ds-tab${tab === 'conversation' ? ' active' : ''}`} onClick={() => setTab('conversation')}>
              이 대화 ({convDatasets.length})
            </button>
            <button className={`rca-ds-tab${tab === 'global' ? ' active' : ''}`} onClick={() => setTab('global')}>
              전체 데이터셋 ({allDatasets.length})
            </button>
          </div>
        )}

        {loading ? (
          <div className="knowledge-empty">로딩 중...</div>
        ) : tab === 'conversation' ? (
          convDatasets.length === 0 ? (
            <div className="knowledge-empty">
              첨부된 데이터셋이 없습니다.<br />
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                "전체 데이터셋" 탭에서 첨부할 수 있습니다.
              </span>
            </div>
          ) : (
            <div className="knowledge-list">
              {convDatasets.map((ds) => renderDatasetRow(ds, { isPrimary: ds.is_primary, showAttachActions: true }))}
            </div>
          )
        ) : (
          allDatasets.length === 0 ? (
            <div className="knowledge-empty">저장된 데이터셋이 없습니다.</div>
          ) : (
            <div className="knowledge-list">
              {allDatasets.map((ds) => renderDatasetRow(ds, { isPrimary: false, showAttachActions: true }))}
            </div>
          )
        )}
      </div>
    </div>
  );
}
