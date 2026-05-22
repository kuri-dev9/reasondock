import React from 'react';
import { OllamaModel } from '../types';

interface Props {
  models: OllamaModel[];
  selectedModel: string;
  onChange: (model: string) => void;
}

export default function ModelSelector({ models, selectedModel, onChange }: Props) {
  return (
    <div className="model-selector">
      <label>모델:</label>
      <select value={selectedModel} onChange={(e) => onChange(e.target.value)}>
        {models.map((m) => {
          const isEmbedding = m.embedding === true;
          const isUnavailable = m.available === false && !isEmbedding;
          const disabled = isEmbedding || isUnavailable;
          const suffix = isEmbedding ? ' (embeddings)' : isUnavailable ? ' (미설정)' : '';
          return (
            <option key={m.name} value={m.name} disabled={disabled}>
              {m.display || m.name}{suffix}
            </option>
          );
        })}
      </select>
    </div>
  );
}
