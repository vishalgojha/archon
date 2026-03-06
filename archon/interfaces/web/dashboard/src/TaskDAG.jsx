(() => {
  const { useEffect, useMemo, useRef, useState } = React;

  const NODE_COLORS = {
    idle: "#6b7280",
    thinking: "#2563eb",
    done: "#16a34a",
    error: "#dc2626",
  };

  function deriveNodesAndEdges(workflow, history) {
    if (Array.isArray(workflow) && workflow.length > 0) {
      const statusByStep = {};
      const outputByStep = {};
      history.forEach((event) => {
        if (event.type === "agent_start") {
          const step = String(event.step_id || event.agent || "");
          if (step) {
            statusByStep[step] = "thinking";
          }
        }
        if (event.type === "agent_end" || event.type === "growth_agent_completed") {
          const step = String(event.step_id || event.agent || "");
          if (step) {
            statusByStep[step] = String(event.status || "done").toLowerCase();
            outputByStep[step] = event.output || event.result || event.payload || null;
          }
        }
      });

      const nodes = workflow.map((step) => ({
        id: String(step.step_id || step.id || step.agent || "step"),
        label: String(step.action || step.agent || step.step_id || "Step"),
        config: step.config || {},
        output: outputByStep[String(step.step_id || step.id || step.agent || "")],
        status: statusByStep[String(step.step_id || step.id || step.agent || "")] || "idle",
      }));
      const edges = [];
      workflow.forEach((step) => {
        const target = String(step.step_id || step.id || step.agent || "");
        (step.dependencies || []).forEach((dep) => {
          edges.push({ source: String(dep), target });
        });
      });
      return { nodes, edges };
    }

    const seen = new Set();
    const nodes = [];
    const edges = [];
    let previous = "task_start";
    nodes.push({ id: "task_start", label: "Task Start", status: "idle", config: {}, output: null });
    history.forEach((event) => {
      if (event.type !== "agent_start" && event.type !== "agent_end" && event.type !== "growth_agent_completed") {
        return;
      }
      const name = String(event.agent || event.agent_name || "").trim();
      if (!name) {
        return;
      }
      if (!seen.has(name)) {
        nodes.push({ id: name, label: name, status: "idle", config: {}, output: null });
        seen.add(name);
      }
      if (event.type === "agent_start") {
        const row = nodes.find((item) => item.id === name);
        if (row) {
          row.status = "thinking";
        }
        edges.push({ source: previous, target: name });
        previous = name;
      }
      if (event.type === "agent_end" || event.type === "growth_agent_completed") {
        const row = nodes.find((item) => item.id === name);
        if (row) {
          row.status = String(event.status || "done").toLowerCase();
          row.output = event.output || event.result || null;
        }
      }
    });
    return { nodes, edges };
  }

  function TaskDAG({ workflow = [], history = [] }) {
    const svgRef = useRef(null);
    const [selectedNode, setSelectedNode] = useState(null);
    const graph = useMemo(() => deriveNodesAndEdges(workflow, history), [workflow, history]);

    useEffect(() => {
      if (!svgRef.current || !window.d3) {
        return undefined;
      }
      const d3 = window.d3;
      const width = svgRef.current.clientWidth || 900;
      const height = svgRef.current.clientHeight || 320;
      const svg = d3.select(svgRef.current);
      svg.selectAll("*").remove();

      svg
        .append("defs")
        .append("marker")
        .attr("id", "dag-arrow")
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 14)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#64748b");

      const nodes = graph.nodes.map((item) => ({ ...item }));
      const edges = graph.edges.map((item) => ({ ...item }));
      const simulation = d3
        .forceSimulation(nodes)
        .force("charge", d3.forceManyBody().strength(-320))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("link", d3.forceLink(edges).id((d) => d.id).distance(120).strength(0.25))
        .force("collision", d3.forceCollide().radius(28));

      const edgeNodes = svg
        .append("g")
        .selectAll("line")
        .data(edges)
        .join("line")
        .attr("stroke", "#475569")
        .attr("stroke-width", 1.5)
        .attr("marker-end", "url(#dag-arrow)");

      const nodeNodes = svg
        .append("g")
        .selectAll("circle")
        .data(nodes)
        .join("circle")
        .attr("r", 16)
        .attr("fill", (d) => NODE_COLORS[String(d.status || "idle")] || NODE_COLORS.idle)
        .style("cursor", "pointer")
        .on("click", (_event, node) => setSelectedNode(node));

      const labels = svg
        .append("g")
        .selectAll("text")
        .data(nodes)
        .join("text")
        .attr("font-size", 11)
        .attr("fill", "#cbd5e1")
        .attr("text-anchor", "middle")
        .text((d) => d.label || d.id);

      simulation.on("tick", () => {
        edgeNodes
          .attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
        nodeNodes.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
        labels.attr("x", (d) => d.x).attr("y", (d) => d.y + 30);
      });

      return () => simulation.stop();
    }, [graph]);

    return (
      <div className="task-dag-shell">
        <div className="task-dag-graph">
          <svg ref={svgRef} aria-label="Task DAG" />
        </div>
        {selectedNode ? (
          <aside className="task-dag-drawer">
            <div className="drawer-header">
              <strong>{selectedNode.label || selectedNode.id}</strong>
              <button type="button" onClick={() => setSelectedNode(null)}>
                x
              </button>
            </div>
            <div className="drawer-body">
              <h4>Config</h4>
              <pre>{JSON.stringify(selectedNode.config || {}, null, 2)}</pre>
              <h4>Output</h4>
              <pre>{JSON.stringify(selectedNode.output || {}, null, 2)}</pre>
            </div>
          </aside>
        ) : null}
      </div>
    );
  }

  window.TaskDAG = TaskDAG;
})();
