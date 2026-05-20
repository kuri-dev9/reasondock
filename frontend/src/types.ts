export interface Reference {
  filename: string;
  score: number;
  matched_summary?: boolean;
  type?: string;
  job_id?: number;
}

export interface PromptMetrics {
  use_uce: boolean;
  fallback_used: boolean;
  original_prompt_tokens?: number | null;
  final_prompt_tokens?: number | null;
  compression_ratio?: number | null;
  build_context_latency_ms?: number | null;
  llm_first_token_ms?: number | null;
  llm_total_latency_ms?: number | null;
  selected_context_count?: number | null;
  dropped_context_count?: number | null;
  intent?: string | null;
  topic_relation?: string | null;
  rca_processing?: RcaProcessingMetrics | null;
}

export interface RcaProcessingMetrics {
  input_xdr_bytes?: number | null;
  structured_summary_json_bytes?: number | null;
  final_result_json_bytes?: number | null;
  result_file_bytes?: number | null;
  xdr_to_summary_ratio?: number | null;
  xdr_to_final_json_ratio?: number | null;
  estimated_reduction_ratio?: number | null;
  final_reduction_ratio?: number | null;
  total_engine_ms?: number | null;
  llm_first_token_ms?: number | null;
  llm_total_latency_ms?: number | null;
  records_per_second?: number | null;
  parsed_records?: number | null;
  skipped_records?: number | null;
  upload_file_deleted?: boolean | null;
  upload_file_delete_error?: string | null;
  stage_ms?: Record<string, number>;
}

export interface Message {
  id: number;
  conversation_id: number;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  references?: Reference[];
  metrics?: PromptMetrics | null;
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

export interface RcaStreamEvent {
  job_id: number;
  step: string;
  progress: number;
  status?: string;
  content?: string;
  token?: string;
  message_id?: number;
  message?: Message;
  metadata?: PromptMetrics;
  error?: string;
}
