import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import ApprovalQueue from "./ApprovalQueue";

test("ApprovalQueue uses live approval handlers", () => {
  const approve = vi.fn();
  const deny = vi.fn();

  render(
    <ApprovalQueue
      stream={{
        pendingApprovals: [
          {
            action_id: "req-1",
            action: "outbound_sms",
            context: { to: "+15550001111" },
            timeout_s: 120,
            created_at: Date.now() / 1000,
          },
        ],
        approve,
        deny,
      }}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  fireEvent.click(screen.getByRole("button", { name: "Deny" }));

  expect(approve).toHaveBeenCalledWith("req-1");
  expect(deny).toHaveBeenCalledWith("req-1");
});
