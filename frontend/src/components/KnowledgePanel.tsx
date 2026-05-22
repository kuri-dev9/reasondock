import React, { useState, useRef, useEffect } from 'react';
import { KnowledgeDoc } from '../types';
import {
  fetchKnowledgeDocs,
  uploadKnowledgeDoc,
  deleteKnowledgeDoc,
  fetchKnowledgeDocStatus,
  fetchKnowledgeDocText,
  fetchKnowledgeDocNormalized,
  fetchKnowledgeDocUceDenoised,
  analyzeKnowledgeDoc,
  updateUserIr,
  restoreGeneratedIr,
} from '../api';

interface Props {
  visible: boolean;
  onClose: () => void;
}

export default function KnowledgePanel({ visible, onClose }: Props) {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Viewer state
  const [viewerDoc, setViewerDoc] = useState<KnowledgeDoc | null>(null);
  const [viewerTab, setViewerTab] = useState<'original' | 'dpe_ir' | 'generated'>('original');
  const [viewerOriginal, setViewerOriginal] = useState('');
  const [viewerUceDenoised, setViewerUceDenoised] = useState('');
  const [viewerNormalized, setViewerNormalized] = useState('');
  const [viewerLoading, setViewerLoading] = useState(false);

  // Edit state
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) loadDocs();
  }, [visible]);

  useEffect(() => {
    const processing = docs.filter((d) => d.status === 'processing');
    if (processing.length === 0) return;

    const interval = setInterval(async () => {
      let updated = false;
      const newDocs = [...docs];
      for (const doc of processing) {
        try {
          const status = await fetchKnowledgeDocStatus(doc.id);
          const idx = newDocs.findIndex((d) => d.id === doc.id);
          if (idx >= 0 && status.status !== 'processing') {
            newDocs[idx] = { ...newDocs[idx], ...status };
            updated = true;
          }
        } catch {}
      }
      if (updated) setDocs(newDocs);
    }, 3000);

    return () => clearInterval(interval);
  }, [docs]);

  const loadDocs = async () => {
    const data = await fetchKnowledgeDocs();
    setDocs(data);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadFile(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const uploadFile = async (file: File) => {
    setUploading(true);
    try {
      const doc = await uploadKnowledgeDoc(file);
      setDocs((prev) => [doc, ...prev]);
    } catch (err: any) {
      alert(err.message || '업로드 실패');
    } finally {
      setUploading(false);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!uploading) setDragActive(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    if (uploading) return;
    const file = e.dataTransfer.files?.[0];
    if (file) await uploadFile(file);
  };

  const handleAnalyze = async (doc: KnowledgeDoc) => {
    setAnalyzingId(doc.id);
    try {
      await analyzeKnowledgeDoc(doc.id);
      await loadDocs();
    } catch (err: any) {
      alert(err.message || 'DPE 분석 실패');
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleViewDoc = async (doc: KnowledgeDoc) => {
    setViewerDoc(doc);
    setViewerTab('original');
    setViewerLoading(true);
    setViewerOriginal('');
    setViewerUceDenoised('');
    setViewerNormalized('');
    setIsEditing(false);
    setEditContent('');
    try {
      const [original, uceResult, normalizedResult] = await Promise.allSettled([
        fetchKnowledgeDocText(doc.id),
        doc.has_uce_denoised ? fetchKnowledgeDocUceDenoised(doc.id) : Promise.reject('없음'),
        doc.has_dpe_ir ? fetchKnowledgeDocNormalized(doc.id) : Promise.reject('없음'),
      ]);
      setViewerOriginal(original.status === 'fulfilled' ? original.value : '로드 실패');
      setViewerUceDenoised(uceResult.status === 'fulfilled' ? uceResult.value : '');
      setViewerNormalized(normalizedResult.status === 'fulfilled' ? normalizedResult.value : '');
    } catch {
      setViewerOriginal('로드 실패');
    } finally {
      setViewerLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('이 문서를 지식 저장소에서 삭제하시겠습니까?')) return;
    await deleteKnowledgeDoc(id);
    setDocs((prev) => prev.filter((d) => d.id !== id));
  };

  // ── Edit handlers ──────────────────────────────────────────────────────

  const handleStartEdit = () => {
    setEditContent(viewerUceDenoised);
    setIsEditing(true);
  };

  const handleSaveEdit = async () => {
    if (!viewerDoc) return;
    setSaving(true);
    try {
      await updateUserIr(viewerDoc.id, editContent);
      setViewerUceDenoised(editContent);
      setIsEditing(false);
      setEditContent('');
      // Update doc status in list without full reload
      setDocs((prev) =>
        prev.map((d) =>
          d.id === viewerDoc.id ? { ...d, dpe_ir_status: 'USER_EDITED' } : d
        )
      );
      setViewerDoc((prev) => prev ? { ...prev, dpe_ir_status: 'USER_EDITED' } : prev);
    } catch (err: any) {
      alert(err.message || '저장 실패');
    } finally {
      setSaving(false);
    }
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditContent('');
  };

  const handleRestoreIr = async () => {
    if (!viewerDoc) return;
    if (!window.confirm('사용자 편집을 버리고 Generated IR로 복원하시겠습니까?')) return;
    try {
      await restoreGeneratedIr(viewerDoc.id);
      setViewerUceDenoised(viewerNormalized);
      setIsEditing(false);
      setEditContent('');
      setDocs((prev) =>
        prev.map((d) =>
          d.id === viewerDoc.id ? { ...d, dpe_ir_status: 'GENERATED' } : d
        )
      );
      setViewerDoc((prev) => prev ? { ...prev, dpe_ir_status: 'GENERATED' } : prev);
    } catch (err: any) {
      alert(err.message || '복원 실패');
    }
  };

  const handleOverlayClick = () => {
    if (isEditing) return;
    setViewerDoc(null);
  };

  // ── Formatting ─────────────────────────────────────────────────────────

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const statusLabel = (doc: KnowledgeDoc) => {
    switch (doc.status) {
      case 'processing': return '처리 중...';
      case 'ready': return `${doc.chunk_count}개 청크`;
      case 'error': return `오류: ${doc.error_message || '알 수 없음'}`;
    }
  };

  if (!visible) return null;

  return (
    <>
      <div className="knowledge-overlay" onClick={onClose}>
        <div className="knowledge-panel" onClick={(e) => e.stopPropagation()}>
          <div className="knowledge-header">
            <h3>지식 저장소</h3>
            <button className="knowledge-close" onClick={onClose}>×</button>
          </div>
          <p className="knowledge-desc">
            문서를 업로드하면 모든 대화에서 자동으로 참조됩니다.
          </p>
          <div
            className={`knowledge-upload${dragActive ? ' drag-active' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <button
              className="knowledge-upload-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? '업로드 중...' : '+ 문서 업로드 또는 드래그'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              className="file-input-hidden"
              onChange={handleUpload}
              accept=".txt,.md,.py,.js,.ts,.json,.csv,.html,.css,.xml,.yaml,.yml,.pdf,.docx,.xlsx,.xls,.hwp,.hwpx,.log,.sh,.sql,.java,.c,.cpp,.h,.go,.rs"
            />
          </div>
          <div className="knowledge-list">
            {docs.length === 0 && (
              <p className="knowledge-empty">등록된 문서가 없습니다.</p>
            )}
            {docs.map((doc) => (
              <div key={doc.id} className="knowledge-item-wrapper">
                <div className="knowledge-item">
                  <div
                    className="knowledge-item-info"
                    onClick={() => setExpandedId(expandedId === doc.id ? null : doc.id)}
                    style={{ cursor: doc.summary ? 'pointer' : 'default' }}
                  >
                    <span className="knowledge-item-name">
                      {doc.summary && (
                        <span className="knowledge-expand-icon">
                          {expandedId === doc.id ? '▾' : '▸'}
                        </span>
                      )}
                      {doc.filename}
                    </span>
                    <span className="knowledge-item-meta">
                      {formatSize(doc.file_size)} · {statusLabel(doc)}
                      {doc.dpe_ir_status === 'RAW_ONLY' && (
                        <span className="dpe-status-badge raw">미분석</span>
                      )}
                      {doc.dpe_ir_status === 'GENERATED' && (
                        <span className="dpe-status-badge generated">DPE IR</span>
                      )}
                      {doc.dpe_ir_status === 'USER_EDITED' && (
                        <span className="dpe-status-badge edited">편집됨</span>
                      )}
                    </span>
                  </div>
                  {doc.status === 'ready' && doc.dpe_ir_status === 'RAW_ONLY' && (
                    <button
                      className="knowledge-item-analyze"
                      onClick={() => handleAnalyze(doc)}
                      disabled={analyzingId === doc.id}
                    >
                      {analyzingId === doc.id ? '분석 중...' : '분석'}
                    </button>
                  )}
                  <button
                    className="knowledge-item-view"
                    onClick={() => handleViewDoc(doc)}
                    disabled={doc.status !== 'ready'}
                  >
                    보기
                  </button>
                  <button
                    className="knowledge-item-delete"
                    onClick={() => handleDelete(doc.id)}
                  >
                    삭제
                  </button>
                </div>
                {expandedId === doc.id && doc.summary && (
                  <div className="knowledge-summary">
                    {doc.summary}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {viewerDoc && (
        <div className="doc-viewer-overlay" onClick={handleOverlayClick}>
          <div className="doc-viewer" onClick={(e) => e.stopPropagation()}>
            <div className="doc-viewer-header">
              <span className="doc-viewer-title">{viewerDoc.filename}</span>
              {viewerDoc.dpe_ir_status && viewerDoc.dpe_ir_status !== 'RAW_ONLY' && (
                <span className={`doc-viewer-type-badge ${
                  viewerDoc.dpe_ir_status === 'USER_EDITED' ? 'badge-edited' : 'badge-dpe'
                }`}>
                  {viewerDoc.dpe_ir_status === 'USER_EDITED' ? 'USER_EDITED' : 'DPE IR'}
                </span>
              )}
              <button
                className="doc-viewer-close"
                onClick={() => { if (!isEditing) setViewerDoc(null); }}
              >
                ×
              </button>
            </div>
            <div className="doc-viewer-tabs">
              <button
                className={`doc-viewer-tab ${viewerTab === 'original' ? 'active' : ''}`}
                onClick={() => { if (!isEditing) setViewerTab('original'); }}
              >
                원본
              </button>
              <button
                className={`doc-viewer-tab ${viewerTab === 'dpe_ir' ? 'active' : ''} ${!viewerDoc?.has_uce_denoised ? 'disabled' : ''}`}
                onClick={() => { if (!isEditing && viewerDoc?.has_uce_denoised) setViewerTab('dpe_ir'); }}
                disabled={!viewerDoc?.has_uce_denoised}
                title={!viewerDoc?.has_uce_denoised ? 'DPE IR 없음 — 먼저 "분석"을 실행하세요' : ''}
              >
                DPE IR
                {viewerDoc?.dpe_ir_status === 'USER_EDITED' && ' (편집됨)'}
                {!viewerDoc?.has_uce_denoised && ' (없음)'}
              </button>
              <button
                className={`doc-viewer-tab ${viewerTab === 'generated' ? 'active' : ''} ${!viewerDoc?.has_dpe_ir ? 'disabled' : ''}`}
                onClick={() => { if (!isEditing && viewerDoc?.has_dpe_ir) setViewerTab('generated'); }}
                disabled={!viewerDoc?.has_dpe_ir}
                title={!viewerDoc?.has_dpe_ir ? 'Generated IR 없음' : 'Generated IR (읽기 전용)'}
              >
                Generated
                {!viewerDoc?.has_dpe_ir && ' (없음)'}
              </button>
            </div>

            <div className="doc-viewer-content">
              {viewerLoading ? (
                <div className="doc-viewer-loading">로딩 중...</div>
              ) : viewerTab === 'original' ? (
                <pre className="doc-viewer-text">{viewerOriginal}</pre>
              ) : viewerTab === 'generated' ? (
                !viewerDoc?.has_dpe_ir ? (
                  <div className="doc-viewer-no-ir">
                    Generated IR이 없습니다.<br />
                    "분석" 버튼을 눌러 DPE 분석을 실행하세요.
                  </div>
                ) : (
                  <pre className="doc-viewer-text">{viewerNormalized}</pre>
                )
              ) : (
                /* dpe_ir tab — active IR, editable */
                !viewerDoc?.has_uce_denoised ? (
                  <div className="doc-viewer-no-ir">
                    DPE IR이 없습니다.<br />
                    "분석" 버튼을 눌러 DPE 분석을 실행하세요.
                  </div>
                ) : (
                  <div className="doc-viewer-ir-container">
                    <div className="doc-viewer-ir-toolbar">
                      {!isEditing ? (
                        <>
                          <button className="ir-btn edit" onClick={handleStartEdit}>편집</button>
                          {viewerDoc?.dpe_ir_status === 'USER_EDITED' && (
                            <button className="ir-btn restore" onClick={handleRestoreIr}>원본 복원</button>
                          )}
                          <span className="ir-status-label">
                            {viewerDoc?.dpe_ir_status === 'USER_EDITED' ? '✏️ 편집됨' : '✓ Generated'}
                          </span>
                        </>
                      ) : (
                        <>
                          <button className="ir-btn save" onClick={handleSaveEdit} disabled={saving}>
                            {saving ? '저장 중...' : '저장'}
                          </button>
                          <button className="ir-btn cancel" onClick={handleCancelEdit} disabled={saving}>취소</button>
                          <span className="ir-status-label">편집 중 — 저장하거나 취소하세요</span>
                        </>
                      )}
                    </div>
                    {isEditing ? (
                      <textarea
                        className="doc-viewer-ir-editor"
                        value={editContent}
                        onChange={(e) => setEditContent(e.target.value)}
                        spellCheck={false}
                      />
                    ) : (
                      <pre className="doc-viewer-text">{viewerUceDenoised}</pre>
                    )}
                  </div>
                )
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
