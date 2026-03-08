import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import MemoryTimeline from "./MemoryTimeline";

test("MemoryTimeline fetches and expands live session memory", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      json: async () => ({
        entries: [
          {
            memory_id: "mem-1",
            timestamp: 1710000000,
            role: "assistant",
            content: "Detailed ARCHON memory entry",
            causal_links: [{ chain_id: "chain-1", effect: "follow_up" }],
            causal_chain: [
              {
                chain_id: "chain-1",
                cause: "lead_created",
                effect: "follow_up",
                confidence: 0.82,
              },
            ],
          },
        ],
      }),
    }),
  );

  render(
    <MemoryTimeline
      stream={{
        sessionId: "session-1",
        apiBase: "http://archon.test",
        memoryRefreshVersion: 1,
      }}
    />,
  );

  const entryButton = await screen.findByRole("button", {
    name: /detailed archon memory entry/i,
  });
  fireEvent.click(entryButton);

  expect(screen.getByText("Memory Detail")).toBeInTheDocument();
  expect(screen.getByText(/lead_created/i)).toBeInTheDocument();
});
