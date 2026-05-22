import { PromptMetrics, RcaAnalyzeResponse, RcaStreamEvent, Reference, SearchResult } from './types';

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

export async function uploadRcaFile(conversationId: number, file: File, useUce = false): Promise<RcaAnalyzeResponse> {
  const formData = new FormData();
  formData.append('conversation_id', String(conversationId));
  formData.append('use_uce', String(useUce));
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
) {
  const controller = new AbortController();

  fetch(`${API_BASE}/conversations/${conversationId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, use_uce: useUce }),
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
