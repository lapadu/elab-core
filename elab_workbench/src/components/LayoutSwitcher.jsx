import React from 'react';
import { Icons } from '../utils/Shared.jsx';

export function LayoutSwitcher({ layout, setLayout }) {
  return (
    <div className="flex">
      <div className="flex items-center bg-slate-800 rounded p-1 gap-1" title="Switch layout">
        <button 
          onClick={() => setLayout('grid-2x2')} 
          className={`p-1.5 rounded transition-all ${layout === 'grid-2x2' ? 'bg-slate-600 text-white shadow-md' : 'text-slate-400 hover:text-white hover:bg-slate-700'}`}
          title="2x2 Grid (4 slots)"
        >
          <Icons.Grid2x2 size={16} />
        </button>
        <button 
          onClick={() => setLayout('grid-pro')} 
          className={`p-1.5 rounded transition-all ${layout === 'grid-pro' ? 'bg-slate-600 text-white shadow-md' : 'text-slate-400 hover:text-white hover:bg-slate-700'}`}
          title="3x2 Grid (6 slots)"
        >
          <Icons.Grid3x2 size={16} />
        </button>
        <button 
          onClick={() => setLayout('grid-5x1')} 
          className={`p-1.5 rounded transition-all ${layout === 'grid-5x1' ? 'bg-slate-600 text-white shadow-md' : 'text-slate-400 hover:text-white hover:bg-slate-700'}`}
          title="5+1 Layout (1 large + 5 small)"
        >
          <Icons.Table2 size={16} />
        </button>
      </div>
    </div>
  );
}
