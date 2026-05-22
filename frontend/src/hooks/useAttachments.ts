import { useState } from 'react';
import { Attachment } from '../types';
import { fetchAttachments, uploadAttachment, deleteAttachment } from '../api';

export function useAttachments() {
  const [attachments, setAttachments] = useState<Attachment[]>([]);

  const loadAttachments = async (convId: number) => {
    try {
      const data = await fetchAttachments(convId);
      setAttachments(data);
    } catch {
      setAttachments([]);
    }
  };

  const handleFileUpload = async (
    file: File,
    activeConvId: number | null,
    getOrCreateConv: () => Promise<number>
  ) => {
    const convId = activeConvId ?? (await getOrCreateConv());
    const att = await uploadAttachment(convId, file);
    setAttachments((prev) => [...prev, att]);
    return convId;
  };

  const handleFileRemove = async (attachmentId: number, activeConvId: number | null) => {
    if (!activeConvId) return;
    await deleteAttachment(activeConvId, attachmentId);
    setAttachments((prev) => prev.filter((a) => a.id !== attachmentId));
  };

  return {
    attachments,
    setAttachments,
    loadAttachments,
    handleFileUpload,
    handleFileRemove,
  };
}
