import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("shows the welcome message and starter status", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Welcome to JobPilot AI" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Project starter is running.",
    );
  });
});
