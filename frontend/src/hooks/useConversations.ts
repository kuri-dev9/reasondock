import { useState, useCallback } from 'react';
import { Conversation, Message, OllamaModel } from '../types';
import {
  fetchConversations,
  createConversation,
  fetchConversation,
  deleteConversation,
  updateConversation,
  fetchModels,
  exportConversation,
  importConversation,
} from '../api';

interface UseConversationsOptions {
  streaming: boolean;
  selectedModel: string;
  setSelectedModel: (model: string) => void;
  currentSystemPrompt: string;
  setCurrentSystemPrompt: (p: string) => void;
  setMessages: (msgs: Message[] | ((prev: Message[]) => Message[])) => void;
  setAttachments: (a: any[]) => void;
  setStreamingContent: (v: string) => void;
  setThinkingContent: (v: string) => void;
  activeConvIdRef: React.MutableRefObject<number | null>;
}

export function useConversations({
  streaming,
  selectedModel,
  setSelectedModel,
  currentSystemPrompt,
  setCurrentSystemPrompt,
  setMessages,
  setAttachments,
  setStreamingContent,
  setThinkingContent,
  activeConvIdRef,
}: UseConversationsOptions) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [models, setModels] = useState<OllamaModel[]>([]);

  const loadConversations = async () => {
    const data = await fetchConversations();
    setConversations(data);
  };

  const loadModels = async () => {
    try {
      const data = await fetchModels();
      setModels(data);
      const available = data.filter((m: OllamaModel) => m.available !== false);
      if (available.length > 0 && !available.find((m: OllamaModel) => m.name === selectedModel)) {
        setSelectedModel(available[0].name);
      }
    } catch {}
  };

  const handleSelectConversation = useCallback(
    async (id: number) => {
      if (streaming) return;
      setActiveConvId(id);
      setMessages([]);
      setStreamingContent('');
      setThinkingContent('');
      const data = await fetchConversation(id);
      if (activeConvIdRef.current === id) {
        setMessages(data.messages || []);
        setSelectedModel(data.model);
        setCurrentSystemPrompt(data.system_prompt || '');
      }
    },
    [streaming]
  );

  const handleCreateConversation = async () => {
    if (streaming) return;
    const conv = await createConversation('새 대화', selectedModel);
    setConversations((prev) => [conv, ...prev]);
    setActiveConvId(conv.id);
    setMessages([]);
    setStreamingContent('');
    setThinkingContent('');
    setAttachments([]);
    setCurrentSystemPrompt('');
    return conv;
  };

  const handleDeleteConversation = async (id: number) => {
    if (streaming) return;
    await deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConvId === id) {
      setActiveConvId(null);
      setMessages([]);
      setAttachments([]);
      setCurrentSystemPrompt('');
    }
  };

  const handleRenameConversation = async (id: number, title: string) => {
    await updateConversation(id, { title });
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
  };

  const handleModelChange = async (model: string) => {
    setSelectedModel(model);
    if (activeConvId) {
      await updateConversation(activeConvId, { model });
    }
  };

  const handleSystemPromptSave = async (prompt: string) => {
    setCurrentSystemPrompt(prompt);
    if (activeConvId) {
      await updateConversation(activeConvId, { system_prompt: prompt || '' });
    } else {
      const conv = await createConversation('새 대화', selectedModel, prompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      setAttachments([]);
    }
  };

  const handleExport = async (id: number, format: 'json' | 'markdown') => {
    try {
      await exportConversation(id, format);
    } catch {
      alert('내보내기에 실패했습니다.');
    }
  };

  const handleImport = async (file: File) => {
    try {
      const conv = await importConversation(file);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      const data = await fetchConversation(conv.id);
      setMessages(data.messages || []);
      setSelectedModel(data.model);
      setCurrentSystemPrompt(data.system_prompt || '');
    } catch (err: any) {
      alert(`가져오기 실패: ${err.message}`);
    }
  };

  return {
    conversations,
    setConversations,
    activeConvId,
    setActiveConvId,
    models,
    loadConversations,
    loadModels,
    handleSelectConversation,
    handleCreateConversation,
    handleDeleteConversation,
    handleRenameConversation,
    handleModelChange,
    handleSystemPromptSave,
    handleExport,
    handleImport,
  };
}
