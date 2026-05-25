// elab_workbench/src/contexts/DispatcherContext.js
import { createContext, useContext } from 'react';
import dispatcher from '../services/DispatcherClient';

const DispatcherContext = createContext(dispatcher);

// eslint-disable-next-line react-refresh/only-export-components
export const useDispatcher = () => {
    return useContext(DispatcherContext);
};

export const DispatcherProvider = ({ children }) => {
    return (
        <DispatcherContext.Provider value={dispatcher}>
            {children}
        </DispatcherContext.Provider>
    );
};
