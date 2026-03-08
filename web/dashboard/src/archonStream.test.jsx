import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";

import { useArchonStream } from "./archonStream";

class MockWebSocket {
  static instances = [];
  static OPEN = 1;
  static CONNECTING = 0;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.sent = [];
    MockWebSocket.instances.push(this);
  }

  send(payload) {
    this.sent.push(payload);
  }

  close(code = 1000) {
    this.readyState = 3;
    this.onclose?.({ code });
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  emit(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function Probe() {
  const stream = useArchonStream({ apiBase: "http://archon.test" });
  return (
    <div>
      <div data-testid="status">{stream.status}</div>
      <div data-testid="rounds">{stream.rounds.length}</div>
      <div data-testid="approvals">{stream.pendingApprovals.length}</div>
      <div data-testid="confidence">{stream.confidence ?? 0}</div>
      <div data-testid="cost">{stream.costState.spent}</div>
      <div data-testid="messages">{stream.messages.length}</div>
    </div>
  );
}

test("useArchonStream bootstraps and normalizes live websocket events", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        token: "token-1",
        session: { session_id: "session-1" },
      }),
    }),
  );
  vi.stubGlobal("WebSocket", MockWebSocket);

  render(<Probe />);

  await waitFor(() => {
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  const socket = MockWebSocket.instances[0];
  act(() => {
    socket.open();
    socket.emit({
      type: "session_restored",
      session: { session_id: "session-1" },
      messages: [{ role: "assistant", content: "Restored" }],
    });
    socket.emit({ type: "agent_start", agent: "ResearcherAgent", started_at: 10 });
    socket.emit({ type: "debate_round_completed", agent: "ResearcherAgent", round: 1, confidence: 72 });
    socket.emit({ type: "cost_update", spent: 1.5, budget: 10 });
    socket.emit({ type: "approval_required", request_id: "req-1", action: "outbound_sms" });
    socket.emit({ type: "done", message: { content: "Finished answer" } });
  });

  expect(screen.getByTestId("status")).toHaveTextContent("connected");
  expect(screen.getByTestId("rounds")).toHaveTextContent("1");
  expect(screen.getByTestId("approvals")).toHaveTextContent("1");
  expect(screen.getByTestId("confidence")).toHaveTextContent("72");
  expect(screen.getByTestId("cost")).toHaveTextContent("1.5");
  expect(screen.getByTestId("messages")).toHaveTextContent("2");
});
