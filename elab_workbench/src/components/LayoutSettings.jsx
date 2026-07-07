import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Icons } from '../utils/Shared.jsx';

const STORAGE_KEY_TEMPLATES = 'elab.v1.layout_templates';

const loadInitialTemplates = () => {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_TEMPLATES);
    if (saved) {
      const parsed = JSON.parse(saved);
      return Array.isArray(parsed) ? parsed : [];
    }
  } catch (error) {
    console.error('Failed to load templates:', error);
  }
  return [];
};

export function LayoutSettings({ slots, layout, onLoadTemplate }) {
  const [templates, setTemplates] = useState(loadInitialTemplates);
  const [templateName, setTemplateName] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState(() => {
    const tmps = loadInitialTemplates();
    return tmps.length > 0 ? tmps[0].id : '';
  });
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [modalPosition, setModalPosition] = useState(null);
  const dragStateRef = useRef({ startX: 0, startY: 0, baseX: 0, baseY: 0 });
  const modalRef = useRef(null);

  useEffect(() => {
    if (!feedback) return undefined;
    const timer = window.setTimeout(() => setFeedback(null), 2500);
    return () => window.clearTimeout(timer);
  }, [feedback]);

  const showFeedback = (type, message) => {
    setFeedback({ type, message });
  };

  const centerModal = () => {
    const modalElement = modalRef.current;
    if (!modalElement) return;

    const width = modalElement.offsetWidth;
    const height = modalElement.offsetHeight;
    const left = Math.max(16, (window.innerWidth - width) / 2);
    const top = Math.max(16, (window.innerHeight - height) / 2);
    setModalPosition({ x: left, y: top });
  };

  const openModal = () => {
    setIsModalOpen(true);
    setFeedback(null);
  };

  const closeModal = () => {
    setIsModalOpen(false);
    setModalPosition(null);
  };

  const startDrag = (event) => {
    if (event.button !== 0) return;
    if (!modalPosition) {
      centerModal();
      return;
    }

    dragStateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      baseX: modalPosition.x,
      baseY: modalPosition.y,
    };

    const dragController = new AbortController();
    const dragSignal = dragController.signal;

    const handlePointerMove = (moveEvent) => {
      const deltaX = moveEvent.clientX - dragStateRef.current.startX;
      const deltaY = moveEvent.clientY - dragStateRef.current.startY;
      const modalElement = modalRef.current;
      const width = modalElement?.offsetWidth || 0;
      const height = modalElement?.offsetHeight || 0;
      const maxX = Math.max(16, window.innerWidth - width - 16);
      const maxY = Math.max(16, window.innerHeight - height - 16);

      setModalPosition({
        x: Math.min(Math.max(16, dragStateRef.current.baseX + deltaX), maxX),
        y: Math.min(Math.max(16, dragStateRef.current.baseY + deltaY), maxY),
      });
    };

    const handlePointerUp = () => {
      dragController.abort();
    };

    window.addEventListener('pointermove', handlePointerMove, { signal: dragSignal });
    window.addEventListener('pointerup', handlePointerUp, { signal: dragSignal });
  };

  const saveTemplate = () => {
    if (!templateName.trim()) {
      showFeedback('error', 'Please enter a template name.');
      return;
    }

    const newTemplate = {
      id: `tpl_${Date.now()}`,
      name: templateName.trim(),
      createdAt: new Date().toISOString(),
      layout,
      slots: JSON.parse(JSON.stringify(slots)), // Deep copy slots state
    };

    const updated = [...templates, newTemplate];
    try {
      localStorage.setItem(STORAGE_KEY_TEMPLATES, JSON.stringify(updated));
      setTemplates(updated);
      setTemplateName('');
      setSelectedTemplate(newTemplate.id);
      showFeedback('success', `Template "${newTemplate.name}" saved.`);
    } catch (error) {
      console.error('Failed to save template:', error);
      showFeedback('error', 'Failed to save template.');
    }
  };

  const deleteTemplate = () => {
    if (!selectedTemplate) return;

    const template = templates.find(t => t.id === selectedTemplate);
    if (!template) return;

    if (window.confirm(`Delete template "${template.name}"?\nThis cannot be undone.`)) {
      const updated = templates.filter(t => t.id !== selectedTemplate);
      try {
        localStorage.setItem(STORAGE_KEY_TEMPLATES, JSON.stringify(updated));
        setTemplates(updated);
        setSelectedTemplate(updated.length > 0 ? updated[0].id : '');
      } catch (error) {
        console.error('Failed to delete template:', error);
        showFeedback('error', 'Failed to delete template.');
      }
    }
  };

  const exportTemplate = () => {
    if (!selectedTemplate) return;
    const template = templates.find(t => t.id === selectedTemplate);
    if (!template) return;

    const dataStr = JSON.stringify(template, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${template.name}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleLoadTemplate = () => {
    if (!selectedTemplate || typeof onLoadTemplate !== 'function') return;
    const template = templates.find(t => t.id === selectedTemplate);
    if (!template) return;

    const result = onLoadTemplate(template);
    if (result?.error) {
      showFeedback('error', result.error);
      return;
    }

    if (result) {
      showFeedback(
        'success',
        `Loaded ${result.loadedCount} tasks${result.missingCount > 0 ? `, ${result.missingCount} missing` : ''}.`
      );
    }
    closeModal();
  };

  const importTemplate = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const imported = JSON.parse(event.target.result);
        if (!imported.name || !imported.slots || !imported.layout) {
          showFeedback('error', 'Invalid template file.');
          return;
        }

        const newTemplate = {
          id: `tpl_${Date.now()}`,
          name: `${imported.name} (imported)`,
          createdAt: new Date().toISOString(),
          layout: imported.layout,
          slots: imported.slots,
        };

        const updated = [...templates, newTemplate];
        localStorage.setItem(STORAGE_KEY_TEMPLATES, JSON.stringify(updated));
        setTemplates(updated);
        setSelectedTemplate(newTemplate.id);
        showFeedback('success', `Template "${newTemplate.name}" imported.`);
      } catch (error) {
        console.error('Failed to import template:', error);
        showFeedback('error', 'Failed to import template file.');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  useEffect(() => {
    if (!isModalOpen) return undefined;

    const timer = window.requestAnimationFrame(() => {
      centerModal();
    });

    return () => window.cancelAnimationFrame(timer);
  }, [isModalOpen]);

  const modal = isModalOpen ? createPortal(
    <div className="fixed inset-0 z-[10000] bg-black/50 pointer-events-auto">
      <div
        ref={modalRef}
        className="absolute bg-slate-900 border border-slate-700 rounded-lg w-96 max-h-[min(32rem,calc(100vh-2rem))] flex flex-col shadow-2xl"
        style={{
          left: modalPosition?.x ?? 16,
          top: modalPosition?.y ?? 16,
        }}
      >
        <div
          className="flex items-center justify-between gap-3 px-4 py-3 border-b border-slate-700 cursor-move select-none"
          onPointerDown={startDrag}
        >
          <div className="flex items-center gap-2 min-w-0">
            <Icons.Move size={14} className="text-slate-500 shrink-0" />
            <h2 className="text-lg font-bold text-slate-200 truncate">Layout Templates</h2>
          </div>
          <button
            onClick={closeModal}
            className="p-1 text-slate-400 hover:text-slate-300 rounded hover:bg-slate-800"
          >
            <Icons.X size={20} />
          </button>
        </div>

        <div className="p-6 overflow-y-auto custom-scrollbar">
          <div className="mb-4 pb-4 border-b border-slate-700">
            <div className="flex gap-2 mb-2">
              <input
                type="text"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && saveTemplate()}
                placeholder="New template name..."
                className="flex-1 bg-slate-950 border border-slate-700 rounded text-xs px-2 py-1.5 outline-none focus:border-blue-500"
              />
              <button
                onClick={saveTemplate}
                className="px-3 py-1.5 bg-green-600 text-white text-xs font-bold rounded hover:bg-green-500 transition-colors"
              >
                Save
              </button>
            </div>
            <div className="flex gap-2">
              <label className="flex-1 px-3 py-1.5 bg-slate-800 text-slate-300 text-xs font-bold rounded hover:bg-slate-700 text-center cursor-pointer">
                Import
                <input
                  type="file"
                  accept=".json"
                  onChange={importTemplate}
                  className="hidden"
                />
              </label>
            </div>
            {feedback && (
              <div className={`mt-3 rounded px-2 py-1.5 text-[11px] ${
                feedback.type === 'error'
                  ? 'bg-red-950/60 text-red-300 border border-red-800/60'
                  : 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/60'
              }`}>
                {feedback.message}
              </div>
            )}
          </div>

          <div className="mb-4 space-y-2">
            {templates.length === 0 ? (
              <div className="text-xs text-slate-500 italic text-center py-4">No templates saved yet</div>
            ) : (
              templates.map(template => (
                <div
                  key={template.id}
                  onClick={() => setSelectedTemplate(template.id)}
                  className={`p-2 rounded border cursor-pointer transition-all text-xs ${
                    selectedTemplate === template.id
                      ? 'bg-blue-600/20 border-blue-500 text-slate-200'
                      : 'bg-slate-800 border-slate-700 text-slate-400 hover:border-slate-600 hover:text-slate-300'
                  }`}
                >
                  <div className="font-semibold truncate">{template.name}</div>
                  <div className="text-[10px] text-slate-600">
                    {template.layout} • {new Date(template.createdAt).toLocaleString()}
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="flex gap-2 pt-4 border-t border-slate-700">
            <button
              onClick={handleLoadTemplate}
              disabled={!selectedTemplate}
              className="flex-1 px-3 py-1.5 bg-blue-600 text-white text-xs font-bold rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Load
            </button>
            <button
              onClick={exportTemplate}
              disabled={!selectedTemplate}
              className="flex-1 px-3 py-1.5 bg-slate-700 text-slate-300 text-xs font-bold rounded hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Export
            </button>
            <button
              onClick={deleteTemplate}
              disabled={!selectedTemplate}
              className="flex-1 px-3 py-1.5 bg-red-600/20 text-red-400 text-xs font-bold rounded hover:bg-red-600/40 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Delete
            </button>
            <button
              onClick={closeModal}
              className="flex-1 px-3 py-1.5 bg-slate-700 text-slate-300 text-xs font-bold rounded hover:bg-slate-600 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  ) : null;

  return (
    <>
      <button
        onClick={openModal}
        className="px-3 py-2 rounded-md font-bold text-xs transition-all border bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700 hover:text-white flex items-center gap-2"
        title="Manage layout templates"
      >
        <Icons.Layout size={14} />
        <span className="hidden sm:inline">Templates</span>
      </button>
      {modal}
    </>
  );
}