import React from "react";
import { render, screen } from "@testing-library/react";

import CostMeter from "./CostMeter";

test("CostMeter renders live budget usage", () => {
  render(
    <CostMeter
      stream={{
        costState: {
          spent: 12.5,
          budget: 25,
          history: [{ spent: 12.5 }],
        },
      }}
    />,
  );

  expect(screen.getByText("50%")).toBeInTheDocument();
  expect(screen.getByText("spent $12.50 of $25.00 budget")).toBeInTheDocument();
});
