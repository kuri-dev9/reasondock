export interface Reference {
  filename: string;
  score: number;
  matched_summary?: boolean;
  type?: string;
  job_id?: number;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  references?: Reference[];
}

export interface Conversation {
  id: number;
  title: string;
  model: string;
  system_prompt?: string | null;
  created_at: string;
  updated_at: string;
  messages?: Message[];
}

export interface OllamaModel {
  name: string;
  provider?: string;
  display?: string;
  available?: boolean;
  size?: number;
  modified_at?: string;
}

export interface Attachment {
  id: number;
  filename: string;
  file_size: number;
  created_at: string;
}

export interface KnowledgeDoc {
  id: number;
  filename: string;
  file_size: number;
  chunk_count: number;
  summary?: string | null;
  status: 'processing' | 'ready' | 'error';
  error_message?: string;
  created_at: string;
}

export interface SearchResult {
  conversation_id: number;
  conversation_title: string;
  message_id: number;
  role: string;
  content_snippet: string;
  created_at: string;
}

export interface RcaJob {
  id: number;
  conversation_id: number;
  filename: string;
  file_size: number;
  status: string;
  progress: number;
  current_step?: string | null;
  error_message?: string | null;
  result_path?: string | null;
  total_records?: number | null;
  parsed_records?: number | null;
  created_at: string;
  updated_at: string;
}

export interface RcaAnalyzeResponse {
  job: RcaJob;
  result?: any;
  message?: Message;
}
