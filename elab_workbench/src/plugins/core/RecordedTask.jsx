import React from 'react';
import { Icons } from '../../utils/Shared.jsx';

// eslint-disable-next-line react-refresh/only-export-components
const RecordedTaskViewer = ({ task, onUpdateTask, isConfigMode }) => {
    // Configuration view shown on the back side of the tile.
    if (isConfigMode) {
        return (
            <div className="p-4 flex flex-col gap-4 text-slate-300">
                <div>
                    <label className="text-xs font-bold text-slate-400 block mb-2">Color</label>
                    <input 
                        type="color" 
                        value={task.color} 
                        onChange={(e) => onUpdateTask({ ...task, color: e.target.value })} 
                        className="w-full h-8 p-0 border-none rounded cursor-pointer bg-slate-800"
                    />
                </div>
                <div>
                    <h4 className="text-xs font-bold text-slate-400 mb-2">Info</h4>
                    <div className="text-xs font-mono bg-slate-950 p-2 rounded">
                        <p>ID: {task.id}</p>
                        <p>Original ID: {task.originalId}</p>
                        <p>Provider ID: {task.providerId}</p>
                    </div>
                </div>
            </div>
        );
    }

    // Default front-side view.
    return (
        <div className="p-4 text-xs text-slate-400 h-full flex flex-col justify-center items-center gap-2">
            <Icons.Archive size={32} className="text-slate-600" />
            <div className="text-center">
                <p className="font-bold text-slate-300">Recorded Source</p>
                <p className="font-mono text-slate-500">{task.originalId}</p>
            </div>
        </div>
    );
};

export const RecordedTaskPlugin = {
    id: 'tpl_rec_default',
    render: RecordedTaskViewer,
    // This plugin is display-only and does not create tasks.
};