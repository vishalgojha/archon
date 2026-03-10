(() => {
  const { useEffect, useRef } = React;

  const STATUS_COLORS = {
    idle: "#8d99ae",
    thinking: "#3a86ff",
    done: "#2a9d8f",
    error: "#e63946",
  };

  function SwarmGraph({ agents = [], edges = [], onNodeClick, selectedAgentId = "" }) {
    const svgRef = useRef(null);
    const markerIdRef = useRef(`swarm-arrow-${Math.random().toString(36).slice(2, 10)}`);

    useEffect(() => {
      if (!svgRef.current || !window.d3) {
        return undefined;
      }

      const d3 = window.d3;
      const width = svgRef.current.clientWidth || 640;
      const height = svgRef.current.clientHeight || 280;
      const svg = d3.select(svgRef.current);
      svg.selectAll("*").remove();
      svg.attr("viewBox", `0 0 ${width} ${height}`);

      if (!agents.length) {
        svg
          .append("text")
          .attr("x", width / 2)
          .attr("y", height / 2)
          .attr("text-anchor", "middle")
          .attr("fill", "#94a3b8")
          .attr("font-size", 12)
          .text("Swarm graph will populate after agent activity starts.");
        return undefined;
      }

      svg
        .append("defs")
        .append("marker")
        .attr("id", markerIdRef.current)
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 16)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#64748b");

      const viewport = svg.append("g").attr("class", "swarm-viewport");

      const simNodes = agents.map((agent) => ({ ...agent }));
      const simEdges = edges.map((edge) => ({ ...edge }));
      const simulation = d3
        .forceSimulation(simNodes)
        .force("charge", d3.forceManyBody().strength(-260))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("link", d3.forceLink(simEdges).id((d) => d.id).distance(115).strength(0.22))
        .force("collision", d3.forceCollide().radius(28));

      const links = viewport
        .append("g")
        .selectAll("line")
        .data(simEdges)
        .join("line")
        .attr("stroke", "#64748b")
        .attr("stroke-width", 1.5)
        .attr("marker-end", `url(#${markerIdRef.current})`);

      const drag = d3
        .drag()
        .on("start", (event, node) => {
          if (!event.active) {
            simulation.alphaTarget(0.22).restart();
          }
          node.fx = node.x;
          node.fy = node.y;
        })
        .on("drag", (event, node) => {
          node.fx = event.x;
          node.fy = event.y;
        })
        .on("end", (event, node) => {
          if (!event.active) {
            simulation.alphaTarget(0);
          }
          node.fx = null;
          node.fy = null;
        });

      const nodes = viewport
        .append("g")
        .selectAll("circle")
        .data(simNodes)
        .join("circle")
        .attr("r", (d) => (d.id === selectedAgentId ? 18 : 16))
        .attr("fill", (d) => STATUS_COLORS[d.status] || STATUS_COLORS.idle)
        .attr("stroke", (d) => (d.id === selectedAgentId ? "#f8fafc" : "rgba(15, 23, 42, 0.85)"))
        .attr("stroke-width", (d) => (d.id === selectedAgentId ? 3 : 1.5))
        .style("cursor", "pointer")
        .on("click", (event, node) => {
          if (onNodeClick) {
            onNodeClick(node, event);
          }
        })
        .call(drag);

      nodes.append("title").text((d) => `${d.label || d.id}\nstatus: ${d.status || "idle"}`);

      const labels = viewport
        .append("g")
        .selectAll("text")
        .data(simNodes)
        .join("text")
        .attr("font-size", 10)
        .attr("fill", "#cbd5e1")
        .attr("text-anchor", "middle")
        .text((d) => d.label || d.id);

      const zoom = d3
        .zoom()
        .scaleExtent([0.65, 2.4])
        .on("zoom", (event) => {
          viewport.attr("transform", event.transform);
        });

      svg.call(zoom);
      svg.call(zoom.transform, d3.zoomIdentity.translate(width * 0.08, height * 0.06).scale(0.94));

      simulation.on("tick", () => {
        links
          .attr("x1", (d) => d.source.x)
          .attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x)
          .attr("y2", (d) => d.target.y);
        nodes.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
        labels.attr("x", (d) => d.x).attr("y", (d) => d.y + 28);
      });

      return () => simulation.stop();
    }, [agents, edges, onNodeClick, selectedAgentId]);

    return <svg ref={svgRef} style={{ width: "100%", height: "100%" }} role="img" aria-label="Swarm graph" />;
  }

  window.SwarmGraph = SwarmGraph;
})();
