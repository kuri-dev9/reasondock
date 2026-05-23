import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { XdrFieldSchema, XdrSchemaProfile } from '../types';
import {
  addXdrField,
  addXdrKeyword,
  createXdrSchemaProfile,
  deleteXdrField,
  deleteXdrKeyword,
  deleteXdrSchemaProfile,
  fetchXdrFields,
  fetchXdrSchemaProfiles,
  setActiveXdrSchema,
  updateXdrField,
  updateXdrSchemaProfile,
} from '../api';

interface Props {
  visible: boolean;
  onClose: () => void;
  selectedSchemaId?: number | null;
  onSchemaChange?: (schema: XdrSchemaProfile | null) => void;
}

type FilterMode = 'all' | 'active' | 'inactive' | 'custom' | 'pii';

interface XdrFieldTreeNode {
  name: string;
  key: string;
  depth: number;
  children: XdrFieldTreeNode[];
  fields: XdrFieldSchema[];
  activeCount: number;
  totalCount: number;
  minOrder: number;
}

const CAPABILITY_KEYS: Array<keyof XdrFieldSchema> = [
  'groupable',
  'filterable',
  'searchable',
  'joinable',
  'sortable',
  'time_series',
  'categorical',
  'boolean_like',
  'pii',
];

function fieldOrder(field: XdrFieldSchema): number {
  return field.spec_index ?? field.spec_no ?? 999999;
}

function fieldTreePath(field: XdrFieldSchema): string[] {
  const explicit = (field.tree_path || []).map((part) => String(part).trim()).filter(Boolean);
  if (explicit.length) return explicit;
  return [field.spec_section || field.category || (field.is_custom ? 'Custom' : 'Uncategorized')].filter(Boolean);
}

function buildFieldTree(fields: XdrFieldSchema[]): XdrFieldTreeNode[] {
  const root: XdrFieldTreeNode = {
    name: 'root',
    key: '',
    depth: -1,
    children: [],
    fields: [],
    activeCount: 0,
    totalCount: 0,
    minOrder: 999999,
  };

  for (const field of fields) {
    let node = root;
    const path = fieldTreePath(field);
    path.forEach((part, depth) => {
      const key = [...path.slice(0, depth), part].join(' / ');
      let child = node.children.find((candidate) => candidate.key === key);
      if (!child) {
        child = {
          name: part,
          key,
          depth,
          children: [],
          fields: [],
          activeCount: 0,
          totalCount: 0,
          minOrder: 999999,
        };
        node.children.push(child);
      }
      node = child;
    });
    node.fields.push(field);
  }

  const summarize = (node: XdrFieldTreeNode) => {
    node.fields.sort((a, b) => fieldOrder(a) - fieldOrder(b) || a.field_name.localeCompare(b.field_name));
    node.minOrder = node.fields[0] ? fieldOrder(node.fields[0]) : 999999;
    node.activeCount = node.fields.filter((field) => field.is_active).length;
    node.totalCount = node.fields.length;
    for (const child of node.children) {
      summarize(child);
      node.minOrder = Math.min(node.minOrder, child.minOrder);
      node.activeCount += child.activeCount;
      node.totalCount += child.totalCount;
    }
    node.children.sort((a, b) => a.minOrder - b.minOrder || a.name.localeCompare(b.name));
  };

  summarize(root);
  return root.children;
}

export default function XdrSchemaPanel({ visible, onClose, selectedSchemaId, onSchemaChange }: Props) {
  const [profiles, setProfiles] = useState<XdrSchemaProfile[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(selectedSchemaId || null);
  const [fields, setFields] = useState<XdrFieldSchema[]>([]);
  const [loading, setLoading] = useState(false);
  const [fieldName, setFieldName] = useState('');
  const [fieldDescription, setFieldDescription] = useState('');
  const [keywordDrafts, setKeywordDrafts] = useState<Record<number, string>>({});
  const [expandedTreeNodes, setExpandedTreeNodes] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<FilterMode>('all');
  const [acting, setActing] = useState(false);

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedId) || null,
    [profiles, selectedId],
  );

  const fieldTree = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = fields.filter((field) => {
      if (filter === 'active' && !field.is_active) return false;
      if (filter === 'inactive' && field.is_active) return false;
      if (filter === 'custom' && !field.is_custom) return false;
      if (filter === 'pii' && !field.pii) return false;
      if (!normalizedQuery) return true;
      const haystack = [
        field.field_name,
        field.description,
        field.role,
        field.category,
        field.spec_section,
        field.spec_sheet,
        ...(field.tree_path || []),
        ...(field.aliases || field.keywords || []),
      ].join(' ').toLowerCase();
      return haystack.includes(normalizedQuery);
    });
    filtered.sort((a, b) => fieldOrder(a) - fieldOrder(b) || a.field_name.localeCompare(b.field_name));
    return buildFieldTree(filtered);
  }, [fields, filter, query]);

  const loadFields = useCallback(async (schemaId: number | null) => {
    if (!schemaId) {
      setFields([]);
      return;
    }
    setFields(await fetchXdrFields(schemaId));
  }, []);

  // Initial load: runs only when panel opens. Preserves existing selectedId if still valid.
  useEffect(() => {
    if (!visible) return;
    (async () => {
      setLoading(true);
      try {
        const data = await fetchXdrSchemaProfiles();
        setProfiles(data);
        setSelectedId((prev) => {
          if (prev && data.find((p) => p.id === prev)) return prev;
          return data.find((p) => p.is_active)?.id || data[0]?.id || null;
        });
      } catch (err: any) {
        alert(err.message || 'xDR 스키마 로드 실패');
      } finally {
        setLoading(false);
      }
    })();
  }, [visible]);

  // Reload fields whenever the selected schema changes.
  useEffect(() => {
    if (visible && selectedId) loadFields(selectedId);
  }, [visible, selectedId, loadFields]);

  const refresh = useCallback(async () => {
    if (!selectedId) return;
    const data = await fetchXdrSchemaProfiles();
    setProfiles(data);
    await loadFields(selectedId);
  }, [selectedId, loadFields]);

  const handleActivate = async () => {
    if (!selectedId) return;
    setActing(true);
    try {
      const profile = await setActiveXdrSchema(selectedId);
      await refresh();
      onSchemaChange?.(profile);
    } catch (err: any) {
      alert(err.message || '활성 스키마 설정 실패');
    } finally {
      setActing(false);
    }
  };

  const handleSaveAsNew = async () => {
    if (!selectedId || !selectedProfile) return;
    const name = window.prompt('새 스키마 이름을 입력하세요.', `${selectedProfile.name} 복사본`);
    if (!name?.trim()) return;
    setActing(true);
    try {
      const profile = await createXdrSchemaProfile(name.trim(), selectedId, selectedProfile.description || undefined);
      setSelectedId(profile.id);
      await refresh();
    } catch (err: any) {
      alert(err.message || '새 스키마 저장 실패');
    } finally {
      setActing(false);
    }
  };

  const handleDeleteProfile = async () => {
    if (!selectedProfile) return;
    if (selectedProfile.is_default) {
      alert('기본 스키마는 삭제할 수 없습니다.');
      return;
    }
    const warning = selectedProfile.dataset_count > 0
      ? `스키마 "${selectedProfile.name}"을(를) 삭제하면 연결된 데이터셋 ${selectedProfile.dataset_count}개도 함께 삭제됩니다.\n\n계속하시겠습니까?`
      : `스키마 "${selectedProfile.name}"을(를) 삭제하시겠습니까?`;
    if (!window.confirm(warning)) return;
    setActing(true);
    try {
      const result = await deleteXdrSchemaProfile(selectedProfile.id);
      alert(`스키마가 삭제되었습니다.${result.deleted_datasets.length ? `\n삭제된 데이터셋: ${result.deleted_datasets.join(', ')}` : ''}`);
      setSelectedId(null);
      await refresh();
      onSchemaChange?.(profiles.find((p) => p.is_active) || null);
    } catch (err: any) {
      alert(err.message || '스키마 삭제 실패');
    } finally {
      setActing(false);
    }
  };

  const handleRename = async () => {
    if (!selectedProfile) return;
    const name = window.prompt('스키마 이름', selectedProfile.name);
    if (!name?.trim() || name.trim() === selectedProfile.name) return;
    setActing(true);
    try {
      await updateXdrSchemaProfile(selectedProfile.id, { name: name.trim() });
      await refresh();
    } catch (err: any) {
      alert(err.message || '스키마 이름 변경 실패');
    } finally {
      setActing(false);
    }
  };

  const handleAddField = async () => {
    if (!selectedId || !fieldName.trim()) return;
    setActing(true);
    try {
      await addXdrField(selectedId, fieldName.trim(), fieldDescription.trim());
      setFieldName('');
      setFieldDescription('');
      await loadFields(selectedId);
    } catch (err: any) {
      alert(err.message || '필드 추가 실패');
    } finally {
      setActing(false);
    }
  };

  const handleFieldPatch = async (field: XdrFieldSchema, data: Partial<XdrFieldSchema>) => {
    setActing(true);
    try {
      await updateXdrField(field.id, data);
      await loadFields(field.schema_id);
    } catch (err: any) {
      alert(err.message || '필드 수정 실패');
    } finally {
      setActing(false);
    }
  };

  const handleDeleteField = async (field: XdrFieldSchema) => {
    if (!window.confirm(`필드 "${field.field_name}"을(를) 삭제하시겠습니까?`)) return;
    setActing(true);
    try {
      await deleteXdrField(field.id);
      await loadFields(field.schema_id);
    } catch (err: any) {
      alert(err.message || '필드 삭제 실패');
    } finally {
      setActing(false);
    }
  };

  const handleAddKeyword = async (field: XdrFieldSchema) => {
    const keyword = (keywordDrafts[field.id] || '').trim();
    if (!keyword) return;
    setActing(true);
    try {
      await addXdrKeyword(field.id, keyword);
      setKeywordDrafts((prev) => ({ ...prev, [field.id]: '' }));
      await loadFields(field.schema_id);
    } catch (err: any) {
      alert(err.message || 'alias 추가 실패');
    } finally {
      setActing(false);
    }
  };

  const handleDeleteKeyword = async (field: XdrFieldSchema, keyword: string) => {
    setActing(true);
    try {
      await deleteXdrKeyword(field.id, keyword);
      await loadFields(field.schema_id);
    } catch (err: any) {
      alert(err.message || 'alias 삭제 실패');
    } finally {
      setActing(false);
    }
  };

  if (!visible) return null;

  return (
    <div className="knowledge-overlay" onClick={onClose}>
      <div className="knowledge-panel xdr-schema-panel" onClick={(e) => e.stopPropagation()}>
        <div className="knowledge-header">
          <h3>xDR 스키마</h3>
          <button className="knowledge-close" onClick={onClose}>×</button>
        </div>

        <div className="xdr-schema-layout">
          <aside className="xdr-schema-sidebar">
            <div className="xdr-schema-sidebar-head">
              <span>저장된 스키마</span>
              <button onClick={handleSaveAsNew} disabled={!selectedId || acting}>새 스키마로 저장</button>
            </div>
            {profiles.map((profile) => (
              <button
                key={profile.id}
                className={`xdr-schema-profile${profile.id === selectedId ? ' active' : ''}`}
                onClick={() => setSelectedId(profile.id)}
              >
                <span>{profile.name}</span>
                <small>
                  {profile.is_active ? '현재 적용' : '저장됨'}
                  {profile.dataset_count ? ` · 데이터셋 ${profile.dataset_count}` : ''}
                </small>
              </button>
            ))}
          </aside>

          <section className="xdr-schema-main">
            {loading || !selectedProfile ? (
              <div className="knowledge-empty">로딩 중...</div>
            ) : (
              <>
                <div className="xdr-schema-toolbar">
                  <div>
                    <strong>{selectedProfile.name}</strong>
                    <span>{selectedProfile.description || '설명 없음'}</span>
                  </div>
                  <div className="xdr-schema-actions">
                    <button onClick={handleRename} disabled={acting}>이름 변경</button>
                    <button onClick={handleActivate} disabled={acting || selectedProfile.is_active}>현재 적용</button>
                    <button className="danger" onClick={handleDeleteProfile} disabled={acting || selectedProfile.is_default}>삭제</button>
                  </div>
                </div>

                <div className="xdr-field-add">
                  <input value={fieldName} onChange={(e) => setFieldName(e.target.value)} placeholder="커스텀 field_name" />
                  <input value={fieldDescription} onChange={(e) => setFieldDescription(e.target.value)} placeholder="설명" />
                  <button onClick={handleAddField} disabled={acting || !fieldName.trim()}>필드 추가</button>
                </div>

                <div className="xdr-field-filters">
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="필드, alias, role 검색" />
                  <select value={filter} onChange={(e) => setFilter(e.target.value as FilterMode)}>
                    <option value="all">전체</option>
                    <option value="active">active</option>
                    <option value="inactive">inactive</option>
                    <option value="custom">custom</option>
                    <option value="pii">PII</option>
                  </select>
                </div>

                <div className="xdr-field-list">
                  {fieldTree.map((node) => (
                    <XdrTreeNode
                      key={node.key}
                      node={node}
                      forceOpen={Boolean(query.trim())}
                      expandedTreeNodes={expandedTreeNodes}
                      setExpandedTreeNodes={setExpandedTreeNodes}
                      acting={acting}
                      keywordDrafts={keywordDrafts}
                      setKeywordDrafts={setKeywordDrafts}
                      onPatch={handleFieldPatch}
                      onDelete={handleDeleteField}
                      onAddKeyword={handleAddKeyword}
                      onDeleteKeyword={handleDeleteKeyword}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function XdrTreeNode({
  node,
  forceOpen,
  expandedTreeNodes,
  setExpandedTreeNodes,
  acting,
  keywordDrafts,
  setKeywordDrafts,
  onPatch,
  onDelete,
  onAddKeyword,
  onDeleteKeyword,
}: {
  node: XdrFieldTreeNode;
  forceOpen: boolean;
  expandedTreeNodes: Record<string, boolean>;
  setExpandedTreeNodes: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  acting: boolean;
  keywordDrafts: Record<number, string>;
  setKeywordDrafts: React.Dispatch<React.SetStateAction<Record<number, string>>>;
  onPatch: (field: XdrFieldSchema, data: Partial<XdrFieldSchema>) => void;
  onDelete: (field: XdrFieldSchema) => void;
  onAddKeyword: (field: XdrFieldSchema) => void;
  onDeleteKeyword: (field: XdrFieldSchema, keyword: string) => void;
}) {
  const isExpanded = forceOpen || expandedTreeNodes[node.key] === true;
  const hasActive = node.activeCount > 0;
  const hasChildren = node.children.length > 0 || node.fields.length > 0;

  return (
    <div className="xdr-tree-node">
      <button
        className={`xdr-tree-header depth-${Math.min(node.depth, 2)}${hasActive ? ' has-active' : ''}`}
        style={{ paddingLeft: `${10 + node.depth * 18}px` }}
        onClick={() => setExpandedTreeNodes((prev) => ({ ...prev, [node.key]: !isExpanded }))}
        disabled={!hasChildren}
      >
        <span className="xdr-tree-label">
          {isExpanded ? '▾' : '▸'} <strong>{node.name}</strong>
        </span>
        <span className={`xdr-active-count${node.activeCount === 0 ? ' zero' : ''}`}>
          {node.activeCount}/{node.totalCount}
        </span>
      </button>
      {isExpanded && (
        <div className="xdr-tree-children">
          {node.children.map((child) => (
            <XdrTreeNode
              key={child.key}
              node={child}
              forceOpen={forceOpen}
              expandedTreeNodes={expandedTreeNodes}
              setExpandedTreeNodes={setExpandedTreeNodes}
              acting={acting}
              keywordDrafts={keywordDrafts}
              setKeywordDrafts={setKeywordDrafts}
              onPatch={onPatch}
              onDelete={onDelete}
              onAddKeyword={onAddKeyword}
              onDeleteKeyword={onDeleteKeyword}
            />
          ))}
          {node.fields.length > 0 && (
            <div className="xdr-tree-fields" style={{ paddingLeft: `${Math.max(node.depth, 0) * 18}px` }}>
              {node.fields.map((field) => (
                <XdrFieldCard
                  key={field.id}
                  field={field}
                  acting={acting}
                  keywordDraft={keywordDrafts[field.id] || ''}
                  onKeywordDraftChange={(value) => setKeywordDrafts((prev) => ({ ...prev, [field.id]: value }))}
                  onPatch={onPatch}
                  onDelete={onDelete}
                  onAddKeyword={onAddKeyword}
                  onDeleteKeyword={onDeleteKeyword}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function XdrFieldCard({
  field,
  acting,
  keywordDraft,
  onKeywordDraftChange,
  onPatch,
  onDelete,
  onAddKeyword,
  onDeleteKeyword,
}: {
  field: XdrFieldSchema;
  acting: boolean;
  keywordDraft: string;
  onKeywordDraftChange: (value: string) => void;
  onPatch: (field: XdrFieldSchema, data: Partial<XdrFieldSchema>) => void;
  onDelete: (field: XdrFieldSchema) => void;
  onAddKeyword: (field: XdrFieldSchema) => void;
  onDeleteKeyword: (field: XdrFieldSchema, keyword: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  const patchText = (key: keyof XdrFieldSchema, original: any) => (
    event: React.FocusEvent<HTMLInputElement | HTMLSelectElement>
  ) => {
    const next = event.target.value.trim() || null;
    if ((next || '') !== (original || '')) onPatch(field, { [key]: next } as Partial<XdrFieldSchema>);
  };

  const aliases = field.aliases || field.keywords || [];

  if (!editing) {
    return (
      <div className={`xdr-field-card${!field.is_active ? ' inactive' : ''}`}>
        <div className="xdr-field-row">
          <label title="planner active">
            <input
              type="checkbox"
              checked={field.is_active}
              onChange={(e) => onPatch(field, { is_active: e.target.checked })}
            />
          </label>
          <span className="xdr-spec-no">#{field.spec_no ?? '-'}</span>
          <span className="xdr-field-name-label">{field.field_name}</span>
          <span className="xdr-field-desc-label">{field.description || '-'}</span>
          <div className="xdr-field-row-actions">
            {aliases.length > 0 && (
              <div className="xdr-keyword-row-compact">
                {aliases.slice(0, 5).map((kw) => (
                  <span key={kw} className="xdr-keyword-chip compact">{kw}</span>
                ))}
                {aliases.length > 5 && (
                  <span className="xdr-keyword-chip compact muted">+{aliases.length - 5}</span>
                )}
              </div>
            )}
            <button className="xdr-edit-btn" onClick={() => setEditing(true)}>편집</button>
            {field.is_custom && (
              <button className="xdr-edit-btn danger" onClick={() => onDelete(field)}>삭제</button>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`xdr-field-card editing${!field.is_active ? ' inactive' : ''}`}>
      <div className="xdr-field-row">
        <label title="planner active">
          <input
            type="checkbox"
            checked={field.is_active}
            onChange={(e) => onPatch(field, { is_active: e.target.checked })}
          />
        </label>
        <span className="xdr-spec-no">#{field.spec_no ?? '-'}</span>
        <input
          className="xdr-field-name"
          defaultValue={field.field_name}
          disabled={!field.is_custom}
          onBlur={(e) => {
            if (e.target.value.trim() && e.target.value !== field.field_name) {
              onPatch(field, { field_name: e.target.value.trim() });
            }
          }}
        />
        <input
          defaultValue={field.description || ''}
          onBlur={(e) => {
            if (e.target.value !== (field.description || '')) onPatch(field, { description: e.target.value });
          }}
          placeholder="description"
        />
        {field.is_custom && <button className="danger" onClick={() => onDelete(field)}>삭제</button>}
      </div>

      <div className="xdr-semantic-row">
        <input defaultValue={field.category || ''} onBlur={patchText('category', field.category)} placeholder="category" />
        <input defaultValue={field.role || ''} onBlur={patchText('role', field.role)} placeholder="role (미분류)" />
        <input defaultValue={field.db_type || ''} onBlur={patchText('db_type', field.db_type)} placeholder="db_type" />
        <input
          defaultValue={field.size ?? ''}
          onBlur={(e) => {
            const value = e.target.value.trim();
            const next = value ? Number(value) : null;
            if ((next ?? null) !== (field.size ?? null)) onPatch(field, { size: next } as Partial<XdrFieldSchema>);
          }}
          placeholder="size"
        />
        <select defaultValue={field.importance || 'low'} onBlur={patchText('importance', field.importance)}>
          <option value="critical">critical</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
      </div>

      <div className="xdr-capability-row">
        {CAPABILITY_KEYS.map((key) => (
          <label key={String(key)}>
            <input
              type="checkbox"
              checked={Boolean(field[key])}
              onChange={(e) => onPatch(field, { [key]: e.target.checked } as Partial<XdrFieldSchema>)}
            />
            {String(key)}
          </label>
        ))}
      </div>

      <div className="xdr-keyword-row">
        {aliases.map((keyword) => (
          <span key={keyword} className="xdr-keyword-chip">
            {keyword}
            <button onClick={() => onDeleteKeyword(field, keyword)}>×</button>
          </span>
        ))}
        <input
          value={keywordDraft}
          onChange={(e) => onKeywordDraftChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onAddKeyword(field); }}
          placeholder="alias 추가"
        />
        <button onClick={() => onAddKeyword(field)} disabled={acting || !keywordDraft.trim()}>추가</button>
      </div>

      <div className="xdr-edit-done">
        <button onClick={() => setEditing(false)}>완료</button>
      </div>
    </div>
  );
}
