import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Reference } from '../types';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  references?: Reference[];
}

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-language">{language}</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? '복사됨' : '복사'}
        </button>
      </div>
      <SyntaxHighlighter style={oneDark} language={language} PreTag="div">
        {children}
      </SyntaxHighlighter>
    </div>
  );
}

export default function ChatMessage({ role, content, references }: Props) {
  return (
    <div className={`message ${role}`}>
      <div className="message-avatar">
        {role === 'user'
          ? <img src="/send_icon.svg" alt="User" className="avatar-icon" />
          : <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />}
      </div>
      <div className="message-content">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ node, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              const inline = !match && !String(children).includes('\n');
              if (inline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              return (
                <CodeBlock language={match ? match[1] : 'text'}>
                  {String(children).replace(/\n$/, '')}
                </CodeBlock>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
        {references && references.length > 0 && (
          <div className="references">
            <span className="references-label">참조 문서</span>
            {references.map((ref, idx) => (
              <span key={idx} className="reference-chip">
                {ref.filename}
                <span className="reference-score">{Math.round(ref.score * 100)}%</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
