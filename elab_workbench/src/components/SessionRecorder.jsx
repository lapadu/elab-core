import React from 'react';
import { Icons } from '../utils/Shared.jsx';

// Format milliseconds as MM:SS.d.
const formatTime = (ms) => {
  if (isNaN(ms) || ms < 0) return "00:00.0";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const millis = Math.floor((ms % 1000) / 100);
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}.${millis}`;
};

export function SessionRecorder({
  sessionState,
  isReplayMode,
  isSessionLoaded,
  sessionName,
  setSessionName,
  sessions,
  selectedSession,
  setSelectedSession,
  handleRecordToggle,
  handleLoadSession,
  handleDeleteSession,
  replayState,
  handleReplayControl,
  seekValue,
  handleSeekChange,
  handleSeekMouseUp,
}) {
  return (
    <>
      {/* LEFT: Session & Transport Controls */}
      <div className="flex items-center gap-4">
        <button
          onClick={handleRecordToggle}
          disabled={isReplayMode}
          className={`flex items-center gap-2 px-3 py-2 rounded-md font-bold text-xs transition-all border ${sessionState.recording ? 'bg-red-500/10 text-red-500 border-red-500/50 hover:bg-red-500/20 animate-pulse' : 'bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700 hover:text-white disabled:opacity-50'}`}
        >
          {sessionState.recording ? <Icons.Square size={14} fill="currentColor" /> : <Icons.Circle size={14} className="text-red-500" />}
          <span>REC</span>
        </button>

        <div className="w-px h-8 bg-slate-800"></div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={(sessionState.recording ? sessionState.sessionId : sessionName) || ''}
            onChange={(e) => setSessionName(e.target.value)}
            disabled={sessionState.recording || isReplayMode}
            className="bg-slate-950 border border-slate-700 rounded text-xs px-2 py-1.5 outline-none w-48 focus:border-blue-500 disabled:opacity-50"
            placeholder="New session name..."
          />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            disabled={sessionState.recording || isSessionLoaded}
            className="bg-slate-950 border border-slate-700 rounded text-xs px-2 py-1.5 outline-none focus:border-blue-500 w-48 disabled:opacity-50"
          >
            {sessions.length === 0 && <option>No sessions found</option>}
            {sessions.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button
            onClick={handleLoadSession}
            disabled={!selectedSession || sessionState.recording}
            className={`px-4 py-1.5 text-xs font-bold rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${isSessionLoaded ? 'bg-red-600 text-white hover:bg-red-500' : 'bg-blue-600 text-white hover:bg-blue-500'}`}
          >
            {isSessionLoaded ? 'Unload' : 'Load'}
          </button>
          <button
            onClick={handleDeleteSession}
            disabled={!selectedSession || sessionState.recording || isSessionLoaded}
            className="p-1.5 text-slate-400 hover:text-red-400 rounded hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Delete selected session"
          >
            <Icons.Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* CENTER: Replay Controls & Progress Bar */}
      <div className={`flex-1 flex items-center gap-3 px-4 transition-opacity ${isReplayMode ? 'opacity-100' : 'opacity-30 pointer-events-none'}`}>
        <div className="flex items-center gap-1">
          <button onClick={() => handleReplayControl(replayState.state === 'playing' ? 'pause' : 'play')} className="p-2 bg-slate-800 text-white rounded-full hover:bg-slate-700 border border-slate-600 shadow-sm disabled:opacity-50" disabled={replayState.state === 'stopped'}>
            {replayState.state === 'playing' ? <Icons.Pause size={18} fill="currentColor" /> : <Icons.Play size={18} fill="currentColor" className="ml-0.5" />}
          </button>
          <button onClick={() => handleReplayControl('stop')} className="p-1.5 text-slate-400 hover:text-red-400 rounded hover:bg-slate-800" title="Stop Replay"><Icons.Square size={16} fill="currentColor" /></button>
        </div>
        <span className="text-xs font-mono text-slate-400 w-16 text-right">{formatTime(seekValue)}</span>

        {/* IMPROVED SCRUBBER: Taller container, bigger handle */}
        <div className="flex-1 relative h-5 flex items-center group">
          <div className="w-full h-1.5 bg-slate-700 rounded-full relative">
            <div
              className="absolute top-0 left-0 h-full bg-blue-600 rounded-full pointer-events-none"
              style={{ width: `${(seekValue / (replayState.duration || 1)) * 100}%` }}>
            </div>
          </div>
          <div
            className="absolute top-1/2 w-4 h-4 bg-white rounded-full -translate-y-1/2 -translate-x-1/2 shadow-lg pointer-events-none group-hover:scale-125 transition-transform"
            style={{ left: `${(seekValue / (replayState.duration || 1)) * 100}%` }}
          ></div>
          <input
            type="range"
            min="0"
            max={replayState.duration || 1}
            step="50" // Smaller step for smoother scrubbing
            value={seekValue}
            onMouseUp={handleSeekMouseUp}
            onChange={handleSeekChange}
            className="absolute inset-0 w-full h-full opacity-0 cursor-grab active:cursor-grabbing"
          />
        </div>

        <span className="text-xs font-mono text-slate-500 w-16">{formatTime(replayState.duration)}</span>
      </div>
    </>
  );
}
