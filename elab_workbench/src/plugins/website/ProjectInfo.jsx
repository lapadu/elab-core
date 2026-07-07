import React from 'react';
import { Icons } from '../../utils/Shared';
import GenericPluginWidget from '../../components/GenericPluginWidget';
import PluginBuilder from '../core/PluginBuilder';

const ProjectInfoWidget = ({ task, isConfigMode, onUpdateTask }) => {
  return (
    <GenericPluginWidget task={task} isConfigMode={isConfigMode} onUpdateTask={onUpdateTask}>
      <div className="p-6 flex-grow flex flex-col justify-between overflow-y-auto custom-scrollbar h-full bg-slate-900/40 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Icons.Info className="text-cyan-500" size={20} />
            <span className="font-bold text-xs uppercase tracking-wider text-slate-100">
              e_Lab Project Info
            </span>
          </div>
          <a
            href="https://github.com/lapadu/elab-core"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 font-bold transition-colors"
          >
            <Icons.Code size={14} />
            GitHub Repo
          </a>
        </div>

        {/* Short Summary & Tagline */}
        <div className="space-y-3">
          <div>
            <h3 className="text-xl font-black text-cyan-400">e_Lab (elektronic Lab)</h3>
            <p className="text-sm font-bold text-slate-200 mt-1 leading-snug">
              Your Flexible, Portable Measurement Lab.
            </p>
          </div>

          {/* Description */}
          <p className="text-xs text-slate-300 leading-relaxed font-medium">
            Transform your custom hardware into a powerful, web-based monitoring and control station. 
            e_Lab connects seamlessly with your sensors, oscilloscopes, and IoT projects—giving you 
            real-time measurement data right in your browser.
          </p>
        </div>

        {/* Tags */}
        <div>
          <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mb-2">
            Tags
          </span>
          <div className="flex flex-wrap gap-1.5">
            {['esp32', 'python', 'nanoframework', 'oszilloskope', 'measurement', 'voltmeter', 'sensor', 'maker', 'iot'].map(tag => (
              <span 
                key={tag} 
                className="text-xs px-2.5 py-0.5 rounded bg-slate-850 border border-slate-800 text-slate-300 font-semibold"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>

        {/* SEO / Meta-Description snippet */}
        <div className="pt-3 border-t border-slate-800/50">
          <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold block mb-1.5">
            SEO / Meta-Description (index.html)
          </span>
          <p className="text-xs text-slate-400 italic leading-relaxed font-medium">
            Turn your hardware into a portable web lab. e-Lab connects sensors, oscilloscopes, and ESP32 projects to a modular workbench for real-time monitoring.
          </p>
        </div>
      </div>
    </GenericPluginWidget>
  );
};

export const ProjectInfoPlugin = new PluginBuilder("website_project_info", "e_Lab Project Info", "UI_TEMPLATE")
  .setRender(ProjectInfoWidget)
  .build();
