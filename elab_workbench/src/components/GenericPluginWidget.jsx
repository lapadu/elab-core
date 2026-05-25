// elab_workbench/src/components/GenericPluginWidget.jsx
import React from 'react';
import { ColorPicker } from '../utils/Shared';

const GenericPluginWidget = ({ task, isConfigMode, onUpdateTask, children, configContent }) => {
    if (isConfigMode) {
        return (
            <div className="p-4 bg-slate-900 h-full overflow-y-auto custom-scrollbar">
                {configContent ? configContent : <ColorPicker task={task} onUpdateTask={onUpdateTask} />}
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-slate-900 text-slate-200 relative">
            {children}
        </div>
    );
};

export default GenericPluginWidget;
