import { useRef } from 'react';
import { Message } from '../types';
import { uploadRcaFile, streamRcaJob } from '../api';
import {
  pickRandom,
  RCA_START_MESSAGES,
  RCA_QUEUED_MESSAGES,
  RCA_PARSING_MESSAGES,
  RCA_ANALYZE_MESSAGES,
} from '../constants/messages';

interface UseRcaOptions {
  activeConvIdRef: React.MutableRefObject<number | null>;
  setMessages: (fn: (prev: Message[]) => Message[]) => void;
  setStreaming: (v: boolean) => void;
  setStreamingContent: (fn: ((prev: string) => string) | string) => void;
  setThinkingContent: (v: string) => void;
  loadConversations: () => Promise<void>;
}

export function useRca({
  activeConvIdRef,
  setMessages,
  setStreaming,
  setStreamingContent,
  setThinkingContent,
  loadConversations,
}: UseRcaOptions) {
  const rcaEventSourceRef = useRef<EventSource | null>(null);

  const handleRcaUpload = async (
    file: File,
    convId: number,
    useUce: boolean,
    schemaId?: number | null,
  ) => {
    const userMsg: Message = {
      id: Date.now(),
      conversation_id: convId,
      role: 'user',
      content: `xDR RCA 분석 요청: ${file.name}`,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [
      ...prev.filter((m) => m.conversation_id === convId),
      userMsg,
    ]);
    setStreaming(true);
    setStreamingContent(pickRandom(RCA_START_MESSAGES));
    setThinkingContent('');

    try {
      const response = await uploadRcaFile(convId, file, useUce, schemaId);
      const source = streamRcaJob(
        response.job.id,
        (event) => {
          const visible = activeConvIdRef.current === convId;
          if (event.step === 'queued' && visible) {
            setStreamingContent(pickRandom(RCA_QUEUED_MESSAGES));
          } else if (event.step === 'parsing' && visible) {
            setStreamingContent(pickRandom(RCA_PARSING_MESSAGES));
          } else if (event.step === 'aggregating' && visible) {
            setStreamingContent('');
          } else if (event.step === 'summary_token' && event.token && visible) {
            setStreamingContent((prev) => prev + event.token);
          } else if (event.step === 'summary_done' && visible) {
            setStreamingContent((prev) => `${prev}\n`);
            setThinkingContent(pickRandom(RCA_ANALYZE_MESSAGES));
          } else if (event.step === 'llm_prepare' && visible) {
            setThinkingContent(pickRandom(RCA_ANALYZE_MESSAGES));
          } else if (event.step === 'llm' && visible) {
            setThinkingContent(pickRandom(RCA_ANALYZE_MESSAGES));
          } else if (event.step === 'llm_token' && event.token && visible) {
            setThinkingContent('');
            setStreamingContent((prev) => prev + event.token);
          } else if (event.step === 'done') {
            source?.close();
            rcaEventSourceRef.current = null;
            if (event.message && visible) {
              setMessages((prev) => [
                ...prev.filter(
                  (m) => !(m.conversation_id === convId && m.id === userMsg.id)
                ),
                userMsg,
                event.message as Message,
              ]);
            }
            if (visible) {
              setStreaming(false);
              setStreamingContent('');
              setThinkingContent('');
            }
            loadConversations();
          } else if (event.step === 'error') {
            source?.close();
            rcaEventSourceRef.current = null;
            if (visible) {
              setStreaming(false);
              setStreamingContent('');
              setThinkingContent('');
              alert(`RCA 분석 실패: ${event.error || '알 수 없는 오류'}`);
            }
          }
        },
        (err) => {
          source?.close();
          rcaEventSourceRef.current = null;
          if (activeConvIdRef.current === convId) {
            setStreaming(false);
            setStreamingContent('');
            setThinkingContent('');
            alert(`RCA 분석 실패: ${err}`);
          }
        }
      );
      rcaEventSourceRef.current = source;
    } catch (err: any) {
      setStreaming(false);
      setStreamingContent('');
      throw err;
    }
  };

  return { handleRcaUpload, rcaEventSourceRef };
}
