import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

const STATUS_COLORS = {
  idle: "#8d99ae",
  thinking: "#3a86ff",
  done: "#2a9d8f",
  error: "#e63946",
};

export default function SwarmGraph({ agents = [], edges = [], onNodeClick }) {
  const svgRef = useRef(null);

  useEffect(() => {
    if (!svgRef.current) {
      return undefined;
    }
    const width = svgRef.current.clientWidth || 900;
    const height = svgRef.current.clientHeight || 520;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    svg
      .append("defs")
      .append("marker")
      .attr("id", "arrow")
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 18)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-5L10,0L0,5")
      .attr("fill", "#64748b");

    const linkGroup = svg.append("g").attr("class", "graph-links");
    const nodeGroup = svg.append("g").attr("class", "graph-nodes");
    const labelGroup = svg.append("g").attr("class", "graph-labels");

    const simNodes = agents.map((agent) => ({ ...agent }));
    const simEdges = edges.map((edge) => ({ ...edge }));
    const simulation = d3
      .forceSimulation(simNodes)
      .force("charge", d3.forceManyBody().strength(-260))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("link", d3.forceLink(simEdges).id((d) => d.id).distance(140).strength(0.2))
      .force("collision", d3.forceCollide().radius(36));

    const links = linkGroup
      .selectAll("line")
      .data(simEdges)
      .join("line")
      .attr("stroke", "#64748b")
      .attr("stroke-width", 1.5)
      .attr("marker-end", "url(#arrow)");

    const nodes = nodeGroup
      .selectAll("circle")
      .data(simNodes)
      .join("circle")
      .attr("r", 16)
      .attr("fill", (d) => STATUS_COLORS[d.status] || STATUS_COLORS.idle)
      .style("cursor", "pointer")
      .on("click", (event, d) => {
        if (onNodeClick) {
          onNodeClick(d, event);
        }
      });

    nodes
      .filter((d) => d.status === "thinking")
      .transition()
      .duration(500)
      .attr("r", 20)
      .transition()
      .duration(500)
      .attr("r", 16)
      .on("end", function pulse() {
        d3.select(this)
          .transition()
          .duration(500)
          .attr("r", 20)
          .transition()
          .duration(500)
          .attr("r", 16)
          .on("end", pulse);
      });

    const labels = labelGroup
      .selectAll("text")
      .data(simNodes)
      .join("text")
      .attr("font-size", 11)
      .attr("fill", "#0f172a")
      .attr("text-anchor", "middle")
      .text((d) => d.label || d.id);

    simulation.on("tick", () => {
      links
        .attr("x1", (d) => d.source.x)
        .attr("y1", (d) => d.source.y)
        .attr("x2", (d) => d.target.x)
        .attr("y2", (d) => d.target.y);
      nodes.attr("cx", (d) => d.x).attr("cy", (d) => d.y);
      labels.attr("x", (d) => d.x).attr("y", (d) => d.y + 30);
    });

    return () => {
      simulation.stop();
    };
  }, [agents, edges, onNodeClick]);

  return <svg ref={svgRef} style={{ width: "100%", height: "100%" }} role="img" aria-label="Swarm graph" />;
}

