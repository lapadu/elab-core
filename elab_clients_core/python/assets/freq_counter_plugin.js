window.registerElabPlugin('SmartFreqCounter', (React, Icons) => {
  const { useState } = React;

  // 7-Segment Digit Component with Decimal Point
  const Digit = ({ val, color, showDot = false }) => {
    const segs = {
      0: [1,1,1,1,1,1,0],
      1: [0,1,1,0,0,0,0],
      2: [1,1,0,1,1,0,1],
      3: [1,1,1,1,0,0,1],
      4: [0,1,1,0,0,1,1],
      5: [1,0,1,1,0,1,1],
      6: [1,0,1,1,1,1,1],
      7: [1,1,1,0,0,0,0],
      8: [1,1,1,1,1,1,1],
      9: [1,1,1,1,0,1,1],
      null: [0,0,0,0,0,0,0]
    };

    const active = segs[val] || segs[null];
    const onStyle = { 
      backgroundColor:color, 
      boxShadow:`0 0 10px ${color}` 
    };
    const offStyle = { 
      backgroundColor:'#334155', 
      opacity:0.2 
    };

    // Style helper
    const s = (idx, t, l, w, h) => ({
      position:'absolute',
      top:t,
      left:l,
      width:w,
      height:h,
      borderRadius: 2,
      ...(active[idx] ? onStyle :offStyle)
    });

    // Decimal point style in the lower-right corner.
    const dotStyle = {
      position:'absolute',
      top:44,
      right:-6,
      width: 4,
      height:4,
      borderRadius:'50%',
      ...(showDot ? onStyle :{ display:'none' })
    };

    return React.createElement('div', { 
      className:"w-8 h-12 relative mx-2 transform -skew-x-6"},  // POSITIVE Neigung + mehr Margin

      React.createElement('div', { style:s(0, 0, 4, 24, 4) }),    // a
      React.createElement('div', { style:s(1, 4, 28, 4, 20) }),   // b
      React.createElement('div', { style: s(2, 28, 28, 4, 20) }),  // c
      React.createElement('div', { style:s(3, 48, 4, 24, 4) }),   // d
      React.createElement('div', { style:s(4, 28, 0, 4, 20) }),   // e
      React.createElement('div', { style:s(5, 4, 0, 4, 20) }),    // f
      React.createElement('div', { style:s(6, 24, 4, 24, 4) }),   // g
      React.createElement('div', { style:dotStyle })              // decimal point
    );
  };

  // Main Widget Component
  return ({ task, dataStreams, isConfigMode }) => {
    const stream = dataStreams[task.originalId] || dataStreams[task.id];
    const rawVal = stream?.value || 0;
    const unit = task.config?.unit || 'N/A';

    // Value formatting
    let valueStr;
    let dotPosition = -1;
    const displayWidth = 7;

    if (unit === '°C') {
      valueStr = rawVal.toFixed(2);
    } else {
      valueStr = Math.round(rawVal).toString();
    }

    const dotIndex = valueStr.indexOf('.');
    if (dotIndex !== -1) {
      // Position des Punkts korrekt berechnen
      dotPosition = displayWidth - valueStr.length + dotIndex;
      valueStr = valueStr.replace('.', ''); // Remove the dot for digit rendering.
    }
    
    const displayString = valueStr.padStart(displayWidth, ' ').slice(-displayWidth);

    if (isConfigMode) 
      return React.createElement('div', { className:'p-4' }, 'Settings:' + task.name);

    return React.createElement('div', {
      className:"h-full flex flex-col p-4 relative overflow-hidden bg-slate-900",
      style:{ background:'linear-gradient(to bottom, #1e293b, #0f172a)' }
    },
      // Header
      React.createElement('div', { 
        className:"flex justify-between items-center mb-6 z-10" 
      },
        React.createElement('div', { className:"flex gap-2 items-center" },
          React.createElement(Icons.Cpu, { size:16, className:"text-purple-400" }),
          React.createElement('span', { 
            className:"text-xs font-bold text-slate-300" 
          }, task.name || "SMART COUNTER")
        ),
        React.createElement('div', { className:"text-[10px] font-mono text-slate-500"}, "v3.2-Buffers")
      ),

      // Display Area
      React.createElement('div', {
        className:"flex-1 flex items-center justify-center bg-black rounded-lg border-4 border-slate-700 shadow-[inset_0_0_20px_black] p-4 z-10"
      },
        displayString.split('').map((char, i) =>
          React.createElement(Digit, {
            key:i,
            val:char === ' ' ? null :parseInt(char),
            color:task.color,
            showDot:i === dotPosition
          })
        ),
        React.createElement('div', {
          className:"ml-4 mt-8 font-mono font-bold text-xl",
          style:{ color: task.color }
        }, unit)
      )
    );
  };
});