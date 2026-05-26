import React, { useState, useEffect, useCallback, useRef } from 'react';
import { ConversationDataset, RcaDataset } from '../types';
import {
  fetchRcaDatasets,
  fetchConversationDatasets,
  attachDataset,
  detachDataset,
  setPrimaryDataset,
  deleteRcaDataset,
  fetchRcaDatasetSummary,
  fetchRcaDatasetDetail,
} from '../api';

interface Props {
  visible: boolean;
  onClose: () => void;
  conversationId?: number | null;
  selectedDatasetId?: string | null;
  onSelectDataset?: (datasetId: string | null) => void;
  onRcaUpload?: (file: File) => Promise<void>;
  onUploadComplete?: (datasetId: string) => void;
}

type Tab = 'conversation' | 'global';

export default function RcaDatasetPanel({ visible, onClose, conversationId, selectedDatasetId, onSelectDataset, onRcaUpload, onUploadComplete }: Props) {
  const [tab, setTab] = useState<Tab>(conversationId ? 'conversation' : 'global');
  const [allDatasets, setAllDatasets] = useState<RcaDataset[]>([]);
  const [convDatasets, setConvDatasets] = useState<ConversationDataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, any>>({});
  const [details, setDetails] = useState<Record<string, { by_interface: any[]; by_cause: any[] } | null>>({});
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [actingOn, setActingOn] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
  }, [visible, conversationId, loadAll]);

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

  const handleLoadDetail = async (datasetId: string) => {
    if (details[datasetId]) { setDetails((p) => ({ ...p, [datasetId]: null })); return; }
    setDetailLoadingId(datasetId);
    try {
      const d = await fetchRcaDatasetDetail(datasetId);
      setDetails((p) => ({ ...p, [datasetId]: d }));
    } catch {
      setDetails((p) => ({ ...p, [datasetId]: { by_interface: [], by_cause: [] } }));
    } finally {
      setDetailLoadingId(null);
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

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !onRcaUpload) return;
    if (fileInputRef.current) fileInputRef.current.value = '';

    setUploading(true);
    try {
      await onRcaUpload(file);

      // RCA job은 비동기로 처리되므로 PROCESSING 포함해서 가장 최근 데이터셋 선택
      const updated = await fetchRcaDatasets();
      setAllDatasets(updated);

      const newest = updated
        .sort((a, b) =>
          new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime()
        )[0];

      if (newest) {
        onSelectDataset?.(newest.dataset_id);
        onUploadComplete?.(newest.dataset_id);
      }
      onClose();  // READY 여부 무관하게 패널 닫기
    } catch (err: any) {
      alert(err.message || 'xDR 업로드 실패');
    } finally {
      setUploading(false);
    }
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

  const renderDetailTable = (rows: any[], keyLabel: string, keyField: string) => {
    if (!rows.length) return <div className="rca-ds-summary-row" style={{ color: 'var(--text-secondary)' }}>데이터 없음</div>;
    return (
      <table className="rca-ds-detail-table">
        <thead><tr><th>{keyLabel}</th><th>건수</th></tr></thead>
        <tbody>
          {rows.map((r: any, i: number) => (
            <tr key={i}><td>{r[keyField] || '(없음)'}</td><td>{r.cnt?.toLocaleString()}</td></tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderSummaryBody = (datasetId: string, summary: any) => {
    if (!summary) return <div className="rca-ds-summary-loading">로딩 중...</div>;
    const overall = summary.overall || {};
    const topFailures = summary.top_failures || [];
    const detail = details[datasetId];
    const loadingDetail = detailLoadingId === datasetId;
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
        <div className="rca-ds-detail-toggle">
          <button
            className="rca-ds-btn"
            onClick={() => handleLoadDetail(datasetId)}
            disabled={loadingDetail}
          >
            {loadingDetail ? '로딩 중...' : detail ? '상세 닫기' : '상세 보기'}
          </button>
        </div>
        {detail && (
          <div className="rca-ds-detail">
            <div className="rca-ds-summary-label">인터페이스별 실패</div>
            {renderDetailTable(detail.by_interface, '인터페이스', 'interface')}
            <div className="rca-ds-summary-label" style={{ marginTop: 8 }}>원인별 실패</div>
            {renderDetailTable(detail.by_cause, '원인 코드', 'cause')}
          </div>
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
          <div className="rca-panel-header-actions">
            {onRcaUpload && (
              <>
                <button
                  className="rca-upload-btn"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  title="xDR .dat 파일 업로드"
                >
                  {uploading ? '업로드 중...' : '+ xDR 업로드'}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".dat"
                  className="file-input-hidden"
                  onChange={handleUpload}
                />
              </>
            )}
            <button className="knowledge-close" onClick={onClose}>×</button>
          </div>
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
