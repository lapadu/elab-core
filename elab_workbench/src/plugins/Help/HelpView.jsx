import { useState, useMemo } from 'react';
import { PLUGIN_REGISTRY } from '../../components/PluginRegistry.jsx';
import { FRONTEND_DEPS, BACKEND_DEPS } from './licenseData.generated.js';
import dispatcher from '../../services/DispatcherClient.js';

/* ── Component ──────────────────────────────────────────────────────── */
export default function HelpView() {
  const [tab, setTab] = useState('help');

  // Collect help content from all registered plugins
  const pluginHelpItems = useMemo(() => {
    return Object.values(PLUGIN_REGISTRY)
      .filter((p) => p.helpContent)
      .map((p) => ({ id: p.id, label: p.label, icon: p.icon, ...p.helpContent }));
  }, []);

  return (
    <div className="h-full flex flex-col gap-4 overflow-auto">
      {/* Tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        {[
          { id: 'help', label: 'Help & Operation' },
          { id: 'licenses-fe', label: 'Licenses (Frontend)' },
          { id: 'licenses-be', label: 'Licenses (Backend)' },
          { id: 'about', label: 'About' },
        ].map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={[
              'px-3 py-1.5 rounded-full text-sm font-medium transition-colors',
              tab === t.id ? 'bg-[var(--sys-state-info)] text-white' : 'bg-gray-200 dark:bg-[var(--sys-background-panel-muted)] text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[var(--sys-surface-interactive)]',
            ].join(' ')}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Help – rendered from plugin helpContent */}
      {tab === 'help' && (
        <div className="max-w-3xl space-y-8">
          {pluginHelpItems.map((ph) => (
            <div key={ph.id}>
              <h2 className="text-lg font-bold mb-3 text-gray-700 dark:text-gray-200 flex items-center gap-2">
                {ph.icon && <span>{ph.icon}</span>}
                {ph.title}
              </h2>
              {ph.sections.map((sec, si) => (
                <div key={si} className="mb-4">
                  <h3 className="text-sm font-bold mb-2 text-gray-600 dark:text-gray-300 uppercase tracking-wide">{sec.heading}</h3>
                  <table className="w-full text-sm border-collapse mb-2">
                    <tbody>
                      {sec.items.map((item, ii) => (
                        <tr key={ii} className="border-b border-gray-100 dark:border-[var(--sys-background-panel-muted)]">
                          <td className="py-1.5 px-3 w-56">
                            <kbd className="bg-gray-100 dark:bg-[var(--sys-surface-default)] text-gray-700 dark:text-gray-200 px-1.5 py-0.5 rounded text-xs font-mono border border-gray-200 dark:border-[var(--sys-surface-interactive)]">
                              {item.keys}
                            </kbd>
                          </td>
                          <td className="py-1.5 px-3 text-gray-600 dark:text-gray-300">{item.desc}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          ))}
          {pluginHelpItems.length === 0 && (
            <p className="text-sm text-gray-400">No plugin help available.</p>
          )}
        </div>
      )}

      {/* Frontend Licenses */}
      {tab === 'licenses-fe' && (
        <LicenseTable title="Frontend Dependencies (npm)" deps={FRONTEND_DEPS} />
      )}

      {/* Backend Licenses */}
      {tab === 'licenses-be' && (
        <LicenseTable title="Backend Dependencies (Python)" deps={BACKEND_DEPS} />
      )}

      {/* About */}
      {tab === 'about' && (
        <div className="max-w-2xl space-y-6">
          <div>
            <h2 className="text-lg font-bold text-gray-700 dark:text-gray-200 mb-3">About e_Lab</h2>
            <div className="flex items-center gap-3 mb-4 bg-gray-50 dark:bg-[var(--sys-surface-default)] p-3 rounded border border-gray-200 dark:border-[var(--sys-surface-interactive)]">
              <div className="text-sm text-gray-600 dark:text-gray-300 font-mono">
                <span className="text-gray-500 dark:text-gray-400">Frontend:</span>{' '}
                <span className="font-bold text-gray-800 dark:text-gray-100">{APP_VERSION}</span>
                {dispatcher.serverVersion && (
                  <>
                    <span className="mx-2 text-gray-400">|</span>
                    <span className="text-gray-500 dark:text-gray-400">Server:</span>{' '}
                    <span className="font-bold text-gray-800 dark:text-gray-100">{dispatcher.serverVersion}</span>
                  </>
                )}
              </div>
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
              e_Lab is a modular measurement and laboratory server. It connects hardware sensors
              (ESP32, Raspberry Pi, simulations) to a React-based workbench via a central dispatcher.
            </p>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              <strong>Technology:</strong> React 19 + Vite (Frontend), Python 3.13 + Flask + Socket.IO + gevent (Backend)
            </p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              © {new Date().getFullYear()} E-Lab Contributors
            </p>
          </div>

          <hr className="border-gray-200 dark:border-[var(--sys-surface-interactive)]" />

          <div>
            <h3 className="text-md font-bold text-gray-700 dark:text-gray-200 mb-2">License</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              <strong>e_Lab</strong> is licensed under the <strong>MIT License</strong>.
            </p>
            <div className="bg-gray-50 dark:bg-[var(--sys-surface-default)] p-3 rounded border border-gray-200 dark:border-[var(--sys-surface-interactive)] text-xs font-mono text-gray-700 dark:text-gray-300 overflow-auto max-h-48 mb-3">
              <pre>{`MIT License

Copyright (c) 2026 E-Lab Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software...

(see LICENSE file in the repository for the full license text)`}</pre>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
              ℹ️ <strong>Build Note:</strong> PyInstaller (GPL-2.0-or-later) is only used at build time,
              not at runtime. This does not affect the MIT license of e_Lab itself.
            </p>
          </div>

          <div>
            <h3 className="text-md font-bold text-gray-700 dark:text-gray-200 mb-2">Dependencies</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-2">
              All dependencies are available under commercially friendly licenses.
              See the <strong>Licenses (Frontend)</strong> and <strong>Licenses (Backend)</strong> tabs for details.
            </p>
            <button
              onClick={() => setTab('licenses-fe')}
              className="inline-block px-3 py-1.5 text-xs font-medium rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50 transition-colors">
              → View All Licenses
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── LicenseTable sub-component ─────────────────────────────────────── */
function LicenseTable({ title, deps }) {
  return (
    <div className="max-w-3xl">
      <h2 className="text-lg font-bold mb-3 text-gray-700 dark:text-gray-200">{title}</h2>
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-200 dark:border-[var(--sys-surface-interactive)]">
            <th className="text-left py-2 px-3 font-semibold text-gray-500 dark:text-gray-400">Package</th>
            <th className="text-left py-2 px-3 font-semibold text-gray-500 dark:text-gray-400">Version</th>
            <th className="text-left py-2 px-3 font-semibold text-gray-500 dark:text-gray-400">License</th>
            <th className="text-left py-2 px-3 font-semibold text-gray-500 dark:text-gray-400">Repository</th>
          </tr>
        </thead>
        <tbody>
          {deps.map((d, i) => (
            <tr key={i} className="border-b border-gray-100 dark:border-[var(--sys-background-panel-muted)] hover:bg-gray-50 dark:hover:bg-[var(--sys-background-panel-elevated)]">
              <td className="py-1.5 px-3 font-medium text-gray-700 dark:text-gray-200">{d.name}</td>
              <td className="py-1.5 px-3 text-gray-500 dark:text-gray-400 tabular-nums">{d.version}</td>
              <td className="py-1.5 px-3">
                <span className="bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded text-xs font-medium">
                  {d.license}
                </span>
              </td>
              <td className="py-1.5 px-3">
                <a href={d.repo} target="_blank" rel="noopener noreferrer"
                  className="text-[var(--sys-state-info)] hover:underline text-xs truncate block max-w-[300px]">
                  {d.repo.replace('https://github.com/', '')}
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
