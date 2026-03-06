(() => {
  const { createContext, useContext } = React;

  const EMPTY_STATE = {
    status: "disconnected",
    connect: () => {},
    disconnect: () => {},
    send: () => {},
    lastEvent: null,
    history: [],
    pendingApprovals: [],
    agentStates: {},
    costState: { spent: 0, budget: 0, history: [] },
  };

  const ARCHONContext = createContext(EMPTY_STATE);

  function ARCHONProvider({ children }) {
    const value = window.useARCHON ? window.useARCHON() : EMPTY_STATE;
    return <ARCHONContext.Provider value={value}>{children}</ARCHONContext.Provider>;
  }

  function useARCHONContext() {
    return useContext(ARCHONContext);
  }

  window.ARCHONContext = ARCHONContext;
  window.useARCHONContext = useARCHONContext;

  const rootElement = document.getElementById("root");
  if (!rootElement) {
    return;
  }

  const root = ReactDOM.createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <ARCHONProvider>{window.App ? <window.App /> : null}</ARCHONProvider>
    </React.StrictMode>,
  );
})();
