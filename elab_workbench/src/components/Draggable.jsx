import React, { useState, useRef, useCallback, useEffect } from 'react';

export const Draggable = ({ children, resetTrigger }) => {
    const dragRef = useRef(null);
    const [position, setPosition] = useState({ x: 0, y: 0 });
    const [isDragging, setIsDragging] = useState(false);
    const startPos = useRef({ x: 0, y: 0 });

    // Reset position when resetTrigger changes. Uses the React-approved
    // "store previous rendering props" pattern so we avoid both ref access
    // during render and setState inside an effect.
    const [prevResetTrigger, setPrevResetTrigger] = useState(resetTrigger);
    if (prevResetTrigger !== resetTrigger) {
        setPrevResetTrigger(resetTrigger);
        if (position.x !== 0 || position.y !== 0) {
            setPosition({ x: 0, y: 0 });
        }
    }

    const onMouseDown = useCallback((e) => {
        if (e.target.closest('.drag-handle') || !e.target.closest('button, a, input, select, textarea')) {
            setIsDragging(true);
            startPos.current = {
                x: e.clientX - position.x,
                y: e.clientY - position.y,
            };
            e.preventDefault();
        }
    }, [position.x, position.y]);

    const onMouseMove = useCallback((e) => {
        if (isDragging && dragRef.current) {
            const newX = e.clientX - startPos.current.x;
            const newY = e.clientY - startPos.current.y;
            setPosition({ x: newX, y: newY });
        }
    }, [isDragging]);

    const onMouseUp = useCallback(() => {
        setIsDragging(false);
    }, []);

    useEffect(() => {
        if (isDragging) {
            window.addEventListener('mousemove', onMouseMove);
            window.addEventListener('mouseup', onMouseUp);
        } else {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        }
        return () => {
            window.removeEventListener('mousemove', onMouseMove);
            window.removeEventListener('mouseup', onMouseUp);
        };
    }, [isDragging, onMouseMove, onMouseUp]);
    
    return (
        <div
            ref={dragRef}
            onMouseDown={onMouseDown}
            style={{
                transform: `translate(${position.x}px, ${position.y}px)`,
                cursor: isDragging ? 'grabbing' : 'grab',
            }}
        >
            {children}
        </div>
    );
};
