import React from 'react';

export function SidebarHeader({ isConnected }) {
  return (
    <div className="h-16 flex items-center px-4 border-b border-slate-800 gap-3">
      <img src="/logo.svg" alt="E-Lab" className="h-12 w-auto" />
      <div className="flex items-center gap-1">
        <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}></span>
        <span className="text-[10px] text-slate-500">{isConnected ? 'Online' : 'Offline'}</span>
      </div>
    </div>
  );
}
