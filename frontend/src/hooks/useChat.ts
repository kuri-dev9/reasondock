import { useRef } from 'react';
import { Message, PromptMetrics } from '../types';
import { streamChat } from '../api';
import { pickRandom, THINKING_MESSAGES } from '../constants/messages';

interface UseChatOptions {
  activeConvIdRef: React.MutableRefObject<number | null>;
  setMessages: (fn: (prev: Message[]) => Message[]) => void;
  setStreaming: (v: boolean) => void;
  setStreamingContent: (fn: ((prev: string) => string) | string) => void;
  setThinkingContent: (v: string) => void;
  setConversations: (fn: (prev: any[]) => any[]) => void;
}

export function useChat({
  activeConvIdRef,
  setMessages,
  setStreaming,
  setStreamingContent,
  setThinkingContent,
  setConversations,
}: UseChatOptions) {
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = (convId: number, message: string, useUce: boolean) => {
    const userMsg: Message = {
      id: Date.now(),
      conversation_id: convId,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => {
      const filtered = prev.filter((m) => m.conversation_id === convId);
      return [...filtered, userMsg];
    });
    setStreaming(true);
    setStreamingContent('');
    setThinkingContent(pickRandom(THINKING_MESSAGES));

    const controller = streamChat(
      convId,
      message,
      useUce,
      (token) => {
        if (activeConvIdRef.current !== convId) return;
        setThinkingContent('');
        setStreamingContent((prev) => prev + token);
      },
      (title, references, metadata?: PromptMetrics) => {
        setStreamingContent((prev) => {
          if (prev) {
            const assistantMsg: Message = {
              id: Date.now() + 1,
              conversation_id: convId,
              role: 'assistant',
              content: prev,
              created_at: new Date().toISOString(),
              references,
              metrics: metadata,
            };
            setMessages((msgs) => [...msgs, assistantMsg]);
          }
          return '';
        });
        setStreaming(false);
        setThinkingContent('');
        abortRef.current = null;
        if (title) {
          setConversations((prev) =>
            prev.map((c) => (c.id === convId ? { ...c, title } : c))
          );
        }
      },
      (err) => {
        setStreamingContent('');
        setThinkingContent('');
        setStreaming(false);
        abortRef.current = null;
        if (err !== 'AbortError') alert(`오류: ${err}`);
      }
    );
    abortRef.current = controller;
  };

  const handleCancel = (
    activeConvId: number | null,
    rcaEventSourceRef: React.MutableRefObject<EventSource | null>
  ) => {
    rcaEventSourceRef.current?.close();
    rcaEventSourceRef.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
    setStreamingContent((prev) => {
      if (prev) {
        const assistantMsg: Message = {
          id: Date.now() + 1,
          conversation_id: activeConvId || 0,
          role: 'assistant',
          content: prev + '\n\n*(응답이 중단되었습니다)*',
          created_at: new Date().toISOString(),
        };
        setMessages((msgs) => [...msgs, assistantMsg]);
      }
      return '';
    });
    setStreaming(false);
    setThinkingContent('');
  };

  return { sendMessage, handleCancel, abortRef };
}
