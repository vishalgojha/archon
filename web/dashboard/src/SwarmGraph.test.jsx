import React from "react";
import { render, screen } from "@testing-library/react";

import SwarmGraph from "./SwarmGraph";

test("SwarmGraph derives agent summary from live stream state", () => {
  render(
    <SwarmGraph
      stream={{
        agentStates: {
          ResearcherAgent: { status: "thinking" },
          CriticAgent: { status: "done" },
        },
        history: [],
      }}
    />,
  );

  expect(screen.getByRole("heading", { name: "Swarm Graph" })).toBeInTheDocument();
  expect(screen.getByText("3 agents, 1 active")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Swarm graph" })).toBeInTheDocument();
});
