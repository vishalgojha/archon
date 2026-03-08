import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import ChatPanel from "./ChatPanel";

test("ChatPanel shows restored messages and sends live input over the stream", () => {
  const send = vi.fn();

  render(
    <ChatPanel
      stream={{
        status: "connected",
        sessionId: "session-1",
        sessionRestored: true,
        messages: [
          { id: "user-1", role: "user", contentType: "default", content: "Hello ARCHON" },
        ],
        activeMessage: {
          id: "assistant-1",
          role: "assistant",
          contentType: "default",
          content: "Working on it",
        },
        send,
      }}
    />,
  );

  expect(screen.getByText("Session restored from previous history.")).toBeInTheDocument();
  expect(screen.getByText("Hello ARCHON")).toBeInTheDocument();
  expect(screen.getByText("Working on it")).toBeInTheDocument();

  fireEvent.change(screen.getByPlaceholderText("Ask ARCHON anything..."), {
    target: { value: "New question" },
  });
  fireEvent.submit(screen.getByRole("button", { name: "Send" }).closest("form"));

  expect(send).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "message",
      session_id: "session-1",
      content: "New question",
    }),
  );
});
