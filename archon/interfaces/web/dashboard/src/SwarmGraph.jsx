(() => {
  const { useEffect, useRef } = React;

  const STATUS_COLORS = {
    idle: "#8d99ae",
    thinking: "#3a86ff",
    done: "#2a9d8f",
    error: "#e63946",
  };

  function SwarmGraph({ agents = [], edges = [], onNodeClick }) {
    const svgRef = useRef(null);

    useEffect(() => {
      if (!svgRef.current || !window.d3) {
        return undefined;
      }

      const d3 = window.d3;
      const width = svgRef.current.clientWidth || 640;
      const height = svgRef.current.clientHeight || 280;
      const svg = d3.select(svgRef.current);
      svg.selectAll("*").remove();

      svg
        .append("defs")
        .append("marker")
        .attr("id", "swarm-arrow")
        .attr("viewBox", "0 -5 10 10")
        .attr("refX", 16)
        .attr("refY", 0)
        .attr("markerWidth", 6)
        .attr("markerHeight", 6)
        .attr("orient", "auto")
        .append("path")
        .attr("d", "M0,-5L10,0L0,5")
        .attr("fill", "#64748b");

      const simNodes = agents.map((agent) => ({ ...agent }));
      const simEdges = edges.map((edge) => ({ ...edge }));
      const simulation = d3
        .forceSimulation(simNodes)
        .force("charge", d3.forceManyBody().strength(-260))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .force("link", d3.forceLink(simEdges).id((d) => d.id).distance(115).strength(0.22))
        .force("collision", d3.forceCollide().radius(28));

      const links = svg
        .append("g")
        .selectAll("line")
        .data(simEdges)
        .join("line")
        .attr("stroke", "#64748b")
        .attr("stroke-width", 1.5)
        .attr("marker-end", "url(#swarm-arrow)");

      const nodes = svg
        .append("g")
        .selectAll("circle")
        .data(simNodes)
        .join("circle")
        .attr("r", 16)
        .attr("fill", (d) => STATUS_COLORS[d.status] || STATUS_COLORS.idle)
        .style("cursor", "pointer")
        .on("click", (event, node) => {
          if (onNodeClick) {
            onNodeClick(node, event);
          }
        });

      const labels = svg
        .append("g")
        .selectAll("text")
        .data(simNodes)
        .join("text")
        .attr("font-size", 10)
        .attr("fill", "#cbd5e1")
        .attr("text-anchor", "middle")
        .text((d) => d.label || d.id);

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
    }, [agents, edges, onNodeClick]);

    return <svg ref={svgRef} style={{ width: "100%", height: "100%" }} role="img" aria-label="Swarm graph" />;
  }

  window.SwarmGraph = SwarmGraph;
})();
