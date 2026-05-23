import React, { useState, useEffect, useRef } from 'react';
import Sidebar from './components/Sidebar';
import ChatMessage from './components/ChatMessage';
import ChatInput from './components/ChatInput';
import ModelSelector from './components/ModelSelector';
import ThemeToggle from './components/ThemeToggle';
import ThinkingIndicator from './components/ThinkingIndicator';
import KnowledgePanel from './components/KnowledgePanel';
import RcaDatasetPanel from './components/RcaDatasetPanel';
import XdrSchemaPanel from './components/XdrSchemaPanel';
import SystemPromptEditor from './components/SystemPromptEditor';
import { useConversations } from './hooks/useConversations';
import { useAttachments } from './hooks/useAttachments';
import { useChat } from './hooks/useChat';
import { useRca } from './hooks/useRca';
import { Message, XdrSchemaProfile } from './types';
import { createConversation, fetchActiveXdrSchemaProfile, fetchKnowledgeDocs, uploadAttachment } from './api';
import './App.css';

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [thinkingContent, setThinkingContent] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [currentSystemPrompt, setCurrentSystemPrompt] = useState('');
  const [dark, setDark] = useState(false);
  const [useUce, setUseUce] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [rcaDatasetPanelOpen, setRcaDatasetPanelOpen] = useState(false);
  const [xdrSchemaPanelOpen, setXdrSchemaPanelOpen] = useState(false);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [selectedXdrSchema, setSelectedXdrSchema] = useState<XdrSchemaProfile | null>(null);
  const [systemPromptOpen, setSystemPromptOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [dropActive, setDropActive] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activeConvIdRef = useRef<number | null>(null);

  // ── Conversations ────────────────────────────────────────────
  const {
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
  } = useConversations({
    streaming,
    selectedModel,
    setSelectedModel,
    currentSystemPrompt,
    setCurrentSystemPrompt,
    setMessages,
    setAttachments: (a) => setAttachments(a),
    setStreamingContent,
    setThinkingContent,
    activeConvIdRef,
  });

  // ── Attachments ──────────────────────────────────────────────
  const { attachments, setAttachments, loadAttachments, handleFileRemove } =
    useAttachments();

  const handleFileUpload = async (file: File) => {
    let convId: number;
    if (!activeConvId) {
      const conv = await createConversation('새 대화', selectedModel, currentSystemPrompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      activeConvIdRef.current = conv.id;
      setMessages([]);
      convId = conv.id;
    } else {
      convId = activeConvId;
    }
    const att = await uploadAttachment(convId, file);
    setAttachments((prev) => [...prev, att]);
  };

  // ── Chat ─────────────────────────────────────────────────────
  const { sendMessage, handleCancel: _handleCancel, abortRef } = useChat({
    activeConvIdRef,
    setMessages,
    setStreaming,
    setStreamingContent,
    setThinkingContent,
    setConversations,
  });

  // ── RCA ──────────────────────────────────────────────────────
  const { handleRcaUpload: _handleRcaUpload, rcaEventSourceRef } = useRca({
    activeConvIdRef,
    setMessages,
    setStreaming,
    setStreamingContent,
    setThinkingContent,
    loadConversations,
  });

  // ── Effects ──────────────────────────────────────────────────
  useEffect(() => { activeConvIdRef.current = activeConvId; }, [activeConvId]);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }, [dark]);
  useEffect(() => { loadConversations(); loadModels(); }, []);
  useEffect(() => {
    fetchActiveXdrSchemaProfile()
      .then(setSelectedXdrSchema)
      .catch(() => setSelectedXdrSchema(null));
  }, []);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);
  useEffect(() => {
    if (activeConvId) loadAttachments(activeConvId);
    else setAttachments([]);
  }, [activeConvId]);

  // ── Wrappers ─────────────────────────────────────────────────
  const handleSend = async (message: string) => {
    if (useUce) {
      const docs = await fetchKnowledgeDocs();
      const processingDocs = docs.filter((d: any) => d.status === 'processing');
      if (processingDocs.length > 0) {
        const names = processingDocs.map((d: any) => d.filename).join(', ');
        const confirmed = window.confirm(
          `지식 저장소에서 신규 문서를 처리하고 있습니다.\n\n처리 중인 문서: ${names}\n\n현재 처리 중인 문서는 이번 프롬프트에 적용되지 않습니다.\n\n계속하시겠습니까?`
        );
        if (!confirmed) return;
      }
    }

    if (!activeConvId) {
      const conv = await createConversation('새 대화', selectedModel, currentSystemPrompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      sendMessage(conv.id, message, useUce, selectedDatasetId);
    } else {
      sendMessage(activeConvId, message, useUce, selectedDatasetId);
    }
  };

  const handleCancel = () => _handleCancel(activeConvId, rcaEventSourceRef);

  const handleMessagesDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (!streaming) setDropActive(true);
  };

  const handleMessagesDragLeave = (e: React.DragEvent) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setDropActive(false);
    }
  };

  const handleMessagesDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDropActive(false);
    if (streaming) return;
    const file = e.dataTransfer.files?.[0];
    if (!file) return;
    if (file.name.toLowerCase().endsWith('.dat')) {
      await handleRcaUpload(file);
    } else {
      await handleFileUpload(file);
    }
  };

  const handleRcaUpload = async (file: File) => {
    let convId: number;
    if (!activeConvId) {
      const conv = await createConversation('RCA 분석', selectedModel, currentSystemPrompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      activeConvIdRef.current = conv.id;
      setMessages([]);
      convId = conv.id;
    } else {
      convId = activeConvId;
    }
    await _handleRcaUpload(file, convId, useUce, selectedXdrSchema?.id || null);
  };

  // ── Render ───────────────────────────────────────────────────
  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onSelect={handleSelectConversation}
        onCreate={handleCreateConversation}
        onDelete={handleDeleteConversation}
        onRename={handleRenameConversation}
        onExport={handleExport}
        onImport={handleImport}
      />
      <main className="main">
        <header className="header">
          <ModelSelector models={models} selectedModel={selectedModel} onChange={handleModelChange} />
          <div className="header-actions">
            <button
              className={`system-prompt-btn ${currentSystemPrompt ? 'has-prompt' : ''}`}
              onClick={() => setSystemPromptOpen(true)}
              title="시스템 프롬프트"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/>
                <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
              </svg>
              {currentSystemPrompt ? '프롬프트 설정됨' : '시스템 프롬프트'}
            </button>
            <button className="knowledge-btn" onClick={() => setKnowledgeOpen(true)} title="지식 저장소">
              <img src="/document_icon.svg" alt="" className="btn-icon" /> 지식 저장소
            </button>
            <button
              className={`header-btn${selectedDatasetId ? ' rca-dataset-active' : ''}`}
              onClick={() => setRcaDatasetPanelOpen(true)}
              title={selectedDatasetId ? `활성 데이터셋: ${selectedDatasetId}` : 'RCA 데이터셋'}
            >
              🔍 {selectedDatasetId
                ? <span className="rca-active-badge">{selectedDatasetId.length > 20 ? selectedDatasetId.slice(0, 20) + '…' : selectedDatasetId}</span>
                : '데이터셋'}
            </button>
            <button
              className={`header-btn${selectedXdrSchema?.is_active ? ' rca-dataset-active' : ''}`}
              onClick={() => setXdrSchemaPanelOpen(true)}
              title={selectedXdrSchema ? `현재 xDR 스키마: ${selectedXdrSchema.name}` : 'xDR 스키마'}
            >
              스키마 {selectedXdrSchema ? <span className="rca-active-badge">{selectedXdrSchema.name}</span> : ''}
            </button>
            <ThemeToggle dark={dark} onToggle={() => setDark(!dark)} />
          </div>
        </header>

        <div
          className={`messages${dropActive ? ' drop-active' : ''}`}
          onDragOver={handleMessagesDragOver}
          onDragLeave={handleMessagesDragLeave}
          onDrop={handleMessagesDrop}
        >
          {dropActive && (
            <div className="drop-overlay">
              <div className="drop-overlay-inner">
                <span className="drop-icon">📎</span>
                <span>.dat → RCA 분석 &nbsp;|&nbsp; 기타 → 첨부</span>
              </div>
            </div>
          )}
          {messages.length === 0 && !streaming && (
            <div className="empty-state">
              <h2>대화를 시작하세요</h2>
              <p>메시지를 입력하면 AI가 답변합니다.</p>
            </div>
          )}
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              role={msg.role}
              content={msg.content}
              references={msg.references}
              metrics={msg.metrics}
            />
          ))}
          {streaming && !streamingContent && thinkingContent && (
            <ThinkingIndicator label={thinkingContent} />
          )}
          {streaming && streamingContent && (
            <>
              <ChatMessage role="assistant" content={streamingContent} />
              {thinkingContent && (
                <ThinkingIndicator label={thinkingContent} />
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        <ChatInput
          onSend={handleSend}
          onCancel={handleCancel}
          onFileUpload={handleFileUpload}
          onRcaUpload={handleRcaUpload}
          onFileRemove={(id) => handleFileRemove(id, activeConvId)}
          attachments={attachments}
          disabled={streaming}
          streaming={streaming}
          useUce={useUce}
          onUseUceChange={setUseUce}
        />
      </main>

      <KnowledgePanel visible={knowledgeOpen} onClose={() => setKnowledgeOpen(false)} />
      <RcaDatasetPanel
        visible={rcaDatasetPanelOpen}
        onClose={() => setRcaDatasetPanelOpen(false)}
        conversationId={activeConvId}
        selectedDatasetId={selectedDatasetId}
        onSelectDataset={setSelectedDatasetId}
      />
      <XdrSchemaPanel
        visible={xdrSchemaPanelOpen}
        onClose={() => setXdrSchemaPanelOpen(false)}
        selectedSchemaId={selectedXdrSchema?.id || null}
        onSchemaChange={setSelectedXdrSchema}
      />
      <SystemPromptEditor
        visible={systemPromptOpen}
        systemPrompt={currentSystemPrompt}
        onSave={handleSystemPromptSave}
        onClose={() => setSystemPromptOpen(false)}
      />
    </div>
  );
}

export default App;
