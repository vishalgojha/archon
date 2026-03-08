import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import DebatePanel from "./DebatePanel";

test("DebatePanel renders live rounds and confidence", () => {
  render(
    <DebatePanel
      stream={{
        rounds: [
          {
            round_id: "round-1",
            role: "ResearcherAgent",
            content: "CAP theorem tradeoff analysis",
          },
        ],
        confidence: 84,
      }}
    />,
  );

  expect(screen.getByText("84%")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /show round/i }));
  expect(screen.getByText("CAP theorem tradeoff analysis")).toBeInTheDocument();
});
