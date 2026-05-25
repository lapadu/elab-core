/* eslint-disable react-refresh/only-export-components */
import React from 'react';
import { 
  Activity, AlertCircle, AlertTriangle, Archive, BarChart2, Calculator, Camera, Check, ChevronDown, ChevronRight, 
  ChevronsLeft, ChevronsRight, Circle, Code, Cpu, Database, Download, Eye, EyeOff, FileCode, FileJson, 
  FileSpreadsheet, Grid, Grid2x2, Grid3x2, Inbox, Info, Layers, Layout, ListChevronsUpDown, ListCollapse, Loader2, Maximize, Maximize2, Minimize, MousePointer2,
  Menu, Move, Palette, Pause, Play, Plus, Radio, RefreshCw, RotateCcw, Save, Send, Server, Settings,
  Sigma, Square, Sidebar, Table, Target, Thermometer, Trash2, Video, Wifi, WifiOff, X, Zap, ChevronsDown, Table2
} from 'lucide-react';

export const COLOR_PALETTE = [
  '#ef4444', '#22c55e', '#f59e0b', '#84cc16',
  '#10b981', '#06b6d4', '#3b82f6', '#6366f1',
  '#8b5cf6', '#d946ef', '#ec4899', '#64748b'
];

export const SYSTEM_COLORS = {
  background: {
    app: '#0f172a',
    panel: '#1e293b',
    panelMuted: '#2d2f31',
    panelElevated: '#2a2c2e'
  },
  surface: {
    default: '#303234',
    subtle: '#334155',
    interactive: '#404244'
  },
  text: {
    primary: '#ffffff',
    secondary: '#94a3b8',
    muted: '#64748b'
  },
  border: {
    default: '#475569',
    strong: '#334155'
  },
  state: {
    info: '#3498db',
    warning: '#f59e0b',
    warningStrong: '#f97316',
    success: '#22c55e',
    danger: '#ef4444',
    focus: '#06b6d4'
  }
};

export const LEGACY_SYSTEM_COLOR_MAP = {
  '#ffffff': SYSTEM_COLORS.text.primary,
  '#2d2f31': SYSTEM_COLORS.background.panelMuted,
  '#334155': SYSTEM_COLORS.surface.subtle,
  '#404244': SYSTEM_COLORS.surface.interactive,
  '#0f172a': SYSTEM_COLORS.background.app,
  '#3498db': SYSTEM_COLORS.state.info,
  '#475569': SYSTEM_COLORS.border.default,
  '#1e293b': SYSTEM_COLORS.background.panel,
  '#2a2c2e': SYSTEM_COLORS.background.panelElevated,
  '#303234': SYSTEM_COLORS.surface.default,
  '#94a3b8': SYSTEM_COLORS.text.secondary,
  '#f97316': SYSTEM_COLORS.state.warningStrong
};

export const SYSTEM_COLOR_CSS_VARS = {
  '--sys-background-app': SYSTEM_COLORS.background.app,
  '--sys-background-panel': SYSTEM_COLORS.background.panel,
  '--sys-background-panel-muted': SYSTEM_COLORS.background.panelMuted,
  '--sys-background-panel-elevated': SYSTEM_COLORS.background.panelElevated,
  '--sys-surface-default': SYSTEM_COLORS.surface.default,
  '--sys-surface-subtle': SYSTEM_COLORS.surface.subtle,
  '--sys-surface-interactive': SYSTEM_COLORS.surface.interactive,
  '--sys-text-primary': SYSTEM_COLORS.text.primary,
  '--sys-text-secondary': SYSTEM_COLORS.text.secondary,
  '--sys-text-muted': SYSTEM_COLORS.text.muted,
  '--sys-border-default': SYSTEM_COLORS.border.default,
  '--sys-border-strong': SYSTEM_COLORS.border.strong,
  '--sys-state-info': SYSTEM_COLORS.state.info,
  '--sys-state-warning': SYSTEM_COLORS.state.warning,
  '--sys-state-warning-strong': SYSTEM_COLORS.state.warningStrong,
  '--sys-state-success': SYSTEM_COLORS.state.success,
  '--sys-state-danger': SYSTEM_COLORS.state.danger,
  '--sys-state-focus': SYSTEM_COLORS.state.focus
};

export function applySystemColorsToRoot(root = typeof document !== 'undefined' ? document.documentElement : null) {
  if (!root) return;
  Object.entries(SYSTEM_COLOR_CSS_VARS).forEach(([cssVar, color]) => {
    root.style.setProperty(cssVar, color);
  });
}

export const Icons = {
    Activity, Settings, Zap, Wifi, Move, Trash2, Maximize2, Save, Radio, Cpu, RotateCcw, 
    Thermometer, Video, Download, RefreshCw, Server, Code, Database, Calculator, Layers, 
    Plus, Layout, Eye, EyeOff, FileJson, X, Grid, Grid2x2, Grid3x2, Sidebar, Table, Target, FileSpreadsheet, Sigma, ChevronRight, 
    ChevronDown, ListChevronsUpDown, ListCollapse, Palette, Play, MousePointer2, Square, Circle, AlertTriangle, Loader2, WifiOff, Pause,
    FileCode, Inbox, AlertCircle, Info, ChevronsLeft, ChevronsRight, Check, Archive, Minimize, Maximize,
    Send, Camera, BarChart2, ChevronsDown, Table2, Menu
};

export const ColorPicker = ({ task, onUpdateTask, label = "Instrument Color" }) => (
  <div className="p-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar">
    <div className="text-xs font-bold text-slate-500 uppercase mb-3">{label}</div>
    <div className="grid grid-cols-6 gap-2">
      {COLOR_PALETTE.map(color => (
        <button
          key={color}
          onClick={() => onUpdateTask({ ...task, color })}
          className={`w-8 h-8 rounded-full border-2 transition-transform hover:scale-110
            ${task.color === color ? 'border-white scale-110 shadow-lg' : 'border-transparent'}`}
          style={{ backgroundColor: color }}
        />
      ))}
    </div>
    <div className="mt-4 p-2 bg-slate-950 rounded text-center border border-slate-800">
      <span className="text-xs text-slate-400 mr-2">Preview:</span>
      <span className="text-lg font-bold font-mono" style={{ color: task.color }}>12.34 V</span>
    </div>
  </div>
);

// --- CUSTOM ICONS ---
export const MSRRackIcon = ({ size = 24, className = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width={size} height={size} className={className}>
    <title>MSR Rack Icon</title>
    <g fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="25" y="10" width="70" height="26" rx="2" />
      <rect x="30" y="18" width="4" height="4" fill="white" stroke="none"/>
      <rect x="30" y="24" width="4" height="4" fill="white" stroke="none"/>
      <circle cx="55" cy="23" r="7" /><line x1="55" y1="23" x2="60" y2="18" strokeWidth="2"/> 
      <circle cx="80" cy="23" r="7" /><line x1="80" y1="23" x2="75" y2="18" strokeWidth="2"/> 
      <rect x="25" y="42" width="70" height="26" rx="2" />
      <rect x="30" y="50" width="4" height="4" fill="white" stroke="none"/>
      <rect x="30" y="56" width="4" height="4" fill="white" stroke="none"/>
      <rect x="40" y="46" width="50" height="18" rx="1" strokeWidth="1.5" opacity="0.6"/>
      <path d="M 42 55 Q 48 45, 54 55 Q 60 65, 66 55 Q 72 45, 78 55 Q 84 65, 90 55" strokeWidth="2"/>
      <rect x="25" y="74" width="70" height="26" rx="2" />
      <rect x="30" y="82" width="4" height="4" fill="white" stroke="none"/>
      <rect x="30" y="88" width="4" height="4" fill="white" stroke="none"/>
      <rect x="40" y="78" width="50" height="18" rx="1" strokeWidth="1.5" />
      <g strokeWidth="2">
         <polyline points="48 83 48 93" />
         <polyline points="54 83 60 83 60 88 54 88 54 93 60 93" />
         <circle cx="64" cy="93" r="1" fill="white" stroke="none"/>
         <polyline points="70 83 70 88 76 88 76 83 76 93" />
      </g>
    </g>
  </svg>
);
export const MSRRackIcon2 = ({ size = 24, className = "" }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    width={size}
    height={size}
    className={className}
    fill="none"
    stroke="currentColor" /* Erlaubt das FÃ¤rben via CSS (z.B. Tailwind: text-blue-500) */
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <title>MSR Rack Icon</title>
    
    {/* Seitliche Rack-Schienen */}
    <path d="M 2 2 v 20 M 22 2 v 20" />

    {/* Modul 1: Messen (Signal/Display) */}
    <rect x="2" y="4" width="20" height="7" rx="1" />
    <polyline 
      points="5,7.5 8,7.5 10.5,5.5 13.5,9.5 16,7.5 19,7.5" 
      strokeWidth="1.5" 
    />

    {/* Modul 2: Regeln (Bedienelemente) */}
    <rect x="2" y="13" width="20" height="7" rx="1" />
    
    {/* Drehregler (links) */}
    <circle cx="7.5" cy="16.5" r="1.5" />
    <path d="M 7.5 16.5 L 8.5 15.5" strokeWidth="1.5" />
    
    {/* Schieberegler (rechts) */}
    <line x1="12.5" y1="16.5" x2="18.5" y2="16.5" strokeWidth="1.5" />
    <line x1="15.5" y1="14.5" x2="15.5" y2="18.5" strokeWidth="1.5" />
  </svg>
);
