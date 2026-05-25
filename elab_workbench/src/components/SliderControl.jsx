// elab_workbench/src/components/SliderControl.jsx
import React from 'react';

const SliderControl = ({ label, value, min, max, step, onChange, unit, colorClass = 'accent-blue-500', textColorClass = 'text-blue-400' }) => {
    return (
        <div className="space-y-1">
            <div className="flex justify-between text-xs text-slate-500 uppercase font-bold">
                <span>{label}</span>
                <span className={textColorClass}>{value} {unit}</span>
            </div>
            <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value}
                onChange={onChange}
                className={`w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer ${colorClass}`}
            />
        </div>
    );
};

export default SliderControl;
