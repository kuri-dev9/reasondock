import { ConversationDataset, PromptMetrics, RcaAnalyzeResponse, RcaDataset, RcaStreamEvent, Reference, SearchResult, XdrFieldSchema, XdrSchemaProfile } from './types';

const API_BASE = '/api';

async function readError(res: Response, fallback: string) {
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      const err = await res.json();
      return err.detail || err.message || fallback;
    } catch {}
  }
  const text = await res.text().catch(() => '');
  if (text.trim().startsWith('<')) {
    return `${fallback} (HTTP ${res.status}: 서버/프록시가 HTML 에러 페이지를 반환했습니다. nginx timeout 또는 backend 로그를 확인하세요.)`;
  }
  return text || `${fallback} (HTTP ${res.status})`;
}

export async function fetchConversations() {
  const res = await fetch(`${API_BASE}/conversations`);
  return res.json();
}

export async function createConversation(title: string, model: string, system_prompt?: string | null) {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, model, system_prompt: system_prompt || null }),
  });
  return res.json();
}

export async function fetchConversation(id: number) {
  const res = await fetch(`${API_BASE}/conversations/${id}`);
  return res.json();
}

export async function updateConversation(id: number, data: { title?: string; model?: string; system_prompt?: string | null }) {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function deleteConversation(id: number) {
  await fetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' });
}

export async function fetchModels() {
  const res = await fetch(`${API_BASE}/models`);
  return res.json();
}

export async function uploadAttachment(conversationId: number, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/attachments`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(await readError(res, '파일 업로드 실패'));
  }
  return res.json();
}

export async function fetchAttachments(conversationId: number) {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/attachments`);
  return res.json();
}

export async function deleteAttachment(conversationId: number, attachmentId: number) {
  await fetch(`${API_BASE}/conversations/${conversationId}/attachments/${attachmentId}`, {
    method: 'DELETE',
  });
}

export async function uploadRcaFile(conversationId: number, file: File, useUce = false, schemaId?: number | null): Promise<RcaAnalyzeResponse> {
  const formData = new FormData();
  formData.append('conversation_id', String(conversationId));
  formData.append('use_uce', String(useUce));
  if (schemaId) formData.append('schema_id', String(schemaId));
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/rca/jobs`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(await readError(res, 'RCA 분석 실패'));
  }
  return res.json();
}

// xDR Field Schema Profiles
export async function fetchXdrSchemaProfiles(): Promise<XdrSchemaProfile[]> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles`);
  if (!res.ok) throw new Error(await readError(res, 'xDR 스키마 목록 로드 실패'));
  return res.json();
}

export async function fetchActiveXdrSchemaProfile(): Promise<XdrSchemaProfile> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles/active`);
  if (!res.ok) throw new Error(await readError(res, '활성 xDR 스키마 로드 실패'));
  return res.json();
}

export async function setActiveXdrSchema(schemaId: number): Promise<XdrSchemaProfile> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles/${schemaId}/active`, { method: 'PATCH' });
  if (!res.ok) throw new Error(await readError(res, '활성 xDR 스키마 설정 실패'));
  return res.json();
}

export async function createXdrSchemaProfile(name: string, sourceSchemaId: number, description?: string): Promise<XdrSchemaProfile> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, source_schema_id: sourceSchemaId, description: description || null }),
  });
  if (!res.ok) throw new Error(await readError(res, 'xDR 스키마 저장 실패'));
  return res.json();
}

export async function updateXdrSchemaProfile(schemaId: number, data: { name?: string; description?: string | null }): Promise<XdrSchemaProfile> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles/${schemaId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readError(res, 'xDR 스키마 수정 실패'));
  return res.json();
}

export async function deleteXdrSchemaProfile(schemaId: number): Promise<{ deleted: number; deleted_datasets: string[] }> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/profiles/${schemaId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await readError(res, 'xDR 스키마 삭제 실패'));
  return res.json();
}

export async function fetchXdrFields(schemaId?: number | null): Promise<XdrFieldSchema[]> {
  const suffix = schemaId ? `?schema_id=${encodeURIComponent(schemaId)}` : '';
  const res = await fetch(`${API_BASE}/rca/xdr-schema${suffix}`);
  if (!res.ok) throw new Error(await readError(res, 'xDR 필드 로드 실패'));
  return res.json();
}

export async function addXdrField(schemaId: number, fieldName: string, description?: string): Promise<XdrFieldSchema> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schema_id: schemaId, field_name: fieldName, description: description || null }),
  });
  if (!res.ok) throw new Error(await readError(res, 'xDR 필드 추가 실패'));
  return res.json();
}

export async function updateXdrField(fieldId: number, data: Partial<XdrFieldSchema>): Promise<XdrFieldSchema> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/${fieldId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await readError(res, 'xDR 필드 수정 실패'));
  return res.json();
}

export async function deleteXdrField(fieldId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/${fieldId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await readError(res, 'xDR 필드 삭제 실패'));
}

export async function addXdrKeyword(fieldId: number, keyword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/${fieldId}/keywords`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }),
  });
  if (!res.ok) throw new Error(await readError(res, 'alias 추가 실패'));
}

export async function deleteXdrKeyword(fieldId: number, keyword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/xdr-schema/${fieldId}/keywords/${encodeURIComponent(keyword)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(await readError(res, 'alias 삭제 실패'));
}

export function streamRcaJob(
  jobId: number,
  onEvent: (event: RcaStreamEvent) => void,
  onError: (err: string) => void,
) {
  const source = new EventSource(`${API_BASE}/rca/jobs/${jobId}/stream`);
  source.onmessage = (event) => {
    try {
      onEvent(JSON.parse(event.data));
    } catch {
      onError('RCA 진행 이벤트를 해석하지 못했습니다.');
      source.close();
    }
  };
  source.onerror = () => {
    onError('RCA 진행 스트림 연결이 끊겼습니다.');
    source.close();
  };
  return source;
}

// RCA Datasets
export async function fetchRcaDatasets(): Promise<RcaDataset[]> {
  const res = await fetch(`${API_BASE}/rca/datasets`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchRcaDataset(datasetId: string): Promise<RcaDataset | null> {
  const res = await fetch(`${API_BASE}/rca/datasets/${datasetId}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchRcaDatasetSummary(datasetId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/rca/datasets/${datasetId}/summary`);
  if (!res.ok) throw new Error('데이터셋 통계 로드 실패');
  return res.json();
}

export async function fetchRcaDatasetDetail(datasetId: string): Promise<{ by_interface: any[]; by_cause: any[] }> {
  const res = await fetch(`${API_BASE}/rca/datasets/${datasetId}/detail`);
  if (!res.ok) throw new Error('데이터셋 상세 분석 로드 실패');
  return res.json();
}

export async function deleteRcaDataset(datasetId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/datasets/${datasetId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await readError(res, '데이터셋 삭제 실패'));
}

// Conversation Dataset Attachments
export async function fetchConversationDatasets(conversationId: number): Promise<ConversationDataset[]> {
  const res = await fetch(`${API_BASE}/rca/conversations/${conversationId}/datasets`);
  if (!res.ok) return [];
  return res.json();
}

export async function attachDataset(conversationId: number, datasetId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/conversations/${conversationId}/datasets/${datasetId}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(await readError(res, '데이터셋 첨부 실패'));
}

export async function detachDataset(conversationId: number, datasetId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/rca/conversations/${conversationId}/datasets/${datasetId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(await readError(res, '데이터셋 분리 실패'));
}

export async function setPrimaryDataset(conversationId: number, datasetId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/rca/conversations/${conversationId}/datasets/${datasetId}/primary`,
    { method: 'PATCH' },
  );
  if (!res.ok) throw new Error(await readError(res, '주 데이터셋 설정 실패'));
}

// Knowledge Base
export async function fetchKnowledgeDocs() {
  const res = await fetch(`${API_BASE}/knowledge`);
  return res.json();
}

export async function uploadKnowledgeDoc(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/knowledge/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(await readError(res, '파일 업로드 실패'));
  }
  return res.json();
}

export async function deleteKnowledgeDoc(id: number) {
  await fetch(`${API_BASE}/knowledge/${id}`, { method: 'DELETE' });
}

export async function fetchKnowledgeDocStatus(id: number) {
  const res = await fetch(`${API_BASE}/knowledge/${id}/status`);
  return res.json();
}

export async function fetchKnowledgeDocText(id: number): Promise<string> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/text`);
  if (!res.ok) throw new Error('원본 텍스트 로드 실패');
  return res.text();
}

export async function fetchKnowledgeDocNormalized(id: number): Promise<string> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/normalized`);
  if (!res.ok) throw new Error('DPE IR 로드 실패');
  return res.text();
}

export async function fetchKnowledgeDocUceDenoised(id: number): Promise<string> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/uce-denoised`);
  if (!res.ok) throw new Error('UCE denoised 로드 실패');
  return res.text();
}

export async function analyzeKnowledgeDoc(id: number): Promise<any> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/analyze`, { method: 'POST' });
  if (!res.ok) throw new Error('DPE 분석 실패');
  return res.json();
}

export async function updateUserIr(id: number, content: string): Promise<any> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/user-ir`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error('저장 실패');
  return res.json();
}

export async function restoreGeneratedIr(id: number): Promise<any> {
  const res = await fetch(`${API_BASE}/knowledge/${id}/restore-ir`, { method: 'POST' });
  if (!res.ok) throw new Error('복원 실패');
  return res.json();
}

// Search
export async function searchConversations(query: string): Promise<SearchResult[]> {
  const res = await fetch(`${API_BASE}/conversations/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json();
}

// Export
export async function exportConversation(id: number, format: 'json' | 'markdown' = 'json') {
  const res = await fetch(`${API_BASE}/conversations/${id}/export?format=${format}`);
  if (!res.ok) throw new Error('내보내기 실패');
  const blob = await res.blob();
  const ext = format === 'json' ? 'json' : 'md';
  const contentDisposition = res.headers.get('Content-Disposition');
  let filename = `conversation.${ext}`;
  if (contentDisposition) {
    const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?(.+)/);
    if (match) filename = decodeURIComponent(match[1]);
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Import
export async function importConversation(file: File) {
  const text = await file.text();
  const data = JSON.parse(text);
  const res = await fetch(`${API_BASE}/conversations/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error(await readError(res, '가져오기 실패'));
  }
  return res.json();
}

export function streamChat(
  conversationId: number,
  message: string,
  useUce: boolean,
  onToken: (token: string) => void,
  onDone: (title?: string, references?: Reference[], metadata?: PromptMetrics) => void,
  onError: (err: string) => void,
  onThinking?: (token: string) => void,
  datasetId?: string | null,
) {
  const controller = new AbortController();

  fetch(`${API_BASE}/conversations/${conversationId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      use_uce: useUce,
      ...(datasetId ? { dataset_id: datasetId } : {}),
    }),
    signal: controller.signal,
  }).then(async (response) => {
    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.thinking && onThinking) onThinking(data.thinking);
            if (data.token) onToken(data.token);
            if (data.done) onDone(data.title || undefined, data.references || undefined, data.metadata || undefined);
            if (data.error) onError(data.error);
          } catch {}
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') onError(err.message);
  });

  return controller;
}
