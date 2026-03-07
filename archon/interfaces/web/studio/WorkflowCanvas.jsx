const { ReactFlow, MiniMap, Controls, Background } = window.ReactFlow;

window.WorkflowCanvas = function WorkflowCanvas({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onNodeClick
}) {
  return React.createElement(
    "div",
    { style: { height: "100%", borderRadius: 20, overflow: "hidden", border: "1px solid rgba(27,43,65,0.1)" } },
    React.createElement(
      ReactFlow,
      {
        nodes,
        edges,
        onNodesChange,
        onEdgesChange,
        onConnect,
        onNodeClick: (_event, node) => onNodeClick(node),
        fitView: true
      },
      React.createElement(MiniMap, { position: "bottom-right" }),
      React.createElement(Controls),
      React.createElement(Background, { gap: 18, size: 1 })
    )
  );
};
