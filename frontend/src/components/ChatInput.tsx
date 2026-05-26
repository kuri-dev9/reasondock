import React, { useState, useRef, useEffect } from 'react';
import { Attachment } from '../types';

interface Props {
  onSend: (message: string) => void;
  onCancel: () => void;
  onFileUpload: (file: File) => Promise<void>;
  onFileRemove: (id: number) => void;
  attachments: Attachment[];
  disabled: boolean;
  streaming: boolean;
  useUce: boolean;
  onUseUceChange: (enabled: boolean) => void;
}

export default function ChatInput({ onSend, onCancel, onFileUpload, onFileRemove, attachments, disabled, streaming, useUce, onUseUceChange }: Props) {
  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragActive] = useState(false);

  // dragActive는 더 이상 ChatInput에서 관리하지 않음 (App.tsx의 messages 영역으로 이동)
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text || disabled) return;
    setInput('');
    onSend(text);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadRegularFile(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const uploadRegularFile = async (file: File) => {
    setUploading(true);
    try {
      await onFileUpload(file);
    } catch (err: any) {
      alert(err.message || '파일 업로드 실패');
    } finally {
      setUploading(false);
    }
  };

  const handleDragOver = (_e: React.DragEvent) => {};
  const handleDragLeave = (_e: React.DragEvent) => {};
  const handleDrop = (_e: React.DragEvent) => {};

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div
      className={`chat-input-wrapper${dragActive ? ' drag-active' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragActive && (
        <div className="chat-drop-hint">
          파일을 놓으면 첨부됩니다. .dat 파일은 RCA 분석으로 처리됩니다.
        </div>
      )}
      <div className="toolbar-bar">
        <div className="toolbar-attachments">
          {attachments.map((att) => (
            <div key={att.id} className="attachment-chip">
              <span className="attachment-icon">📎</span>
              <span className="attachment-name">{att.filename}</span>
              <span className="attachment-size">({formatSize(att.file_size)})</span>
              <button
                className="attachment-remove"
                onClick={() => onFileRemove(att.id)}
                disabled={disabled}
              >×</button>
            </div>
          ))}
        </div>
        <label className={`uce-toggle ${useUce ? 'enabled' : ''}`}>
          <input
            type="checkbox"
            checked={useUce}
            onChange={(e) => onUseUceChange(e.target.checked)}
            disabled={disabled}
          />
          <span>향상된 프롬프트</span>
        </label>
      </div>
      <div className="chat-input-container">
        <button
          className="attach-btn"
          onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
          disabled={disabled || uploading}
          title="파일 첨부"
        >
          {uploading ? '⏳' : '📎'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="file-input-hidden"
          onChange={handleFileChange}
          accept=".txt,.md,.py,.js,.ts,.jsx,.tsx,.json,.csv,.html,.css,.xml,.yaml,.yml,.pdf,.docx,.xlsx,.xls,.hwp,.hwpx,.log,.sh,.sql,.java,.c,.cpp,.h,.go,.rs"
        />
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="메시지를 입력하세요... (Shift+Enter로 줄바꿈)"
          disabled={disabled}
          rows={1}
        />
        {streaming ? (
          <button className="cancel-btn" onClick={onCancel}>
            중지
          </button>
        ) : (
          <button className="send-btn" onClick={handleSubmit} disabled={disabled || !input.trim()}>
            전송
          </button>
        )}
      </div>
    </div>
  );
}
