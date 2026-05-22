import React from 'react';

interface Props {
  label: string;
}

export default function ThinkingIndicator({ label }: Props) {
  return (
    <div className="message assistant">
      <div className="message-avatar">
        <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />
      </div>
      <div className="message-content thinking-indicator">
        <span className="thinking-label">{label}</span>
      </div>
    </div>
  );
}
