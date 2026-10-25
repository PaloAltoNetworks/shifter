import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModelSourcePicker } from "./ModelSourcePicker";

vi.mock("@/api/model-sources", () => ({ useModelSourceOptions: () => ({ data: {
  available: true, workspace: "workspace-one", workspaces: [{ uuid: "workspace-one", name: "Workshop", organization_name: "Tenant", is_personal: false }],
  aliases: [{ logical_alias: "coding-main", multiple_allowed: true, sources: [
    { id: "one", revision: 2, configuration: { name: "First account", provider: "anthropic-v1", model: "model-a", region: "provider-managed", currency: "USD", input_price_per_million: 1000000, output_price_per_million: 3000000 } },
    { id: "two", revision: 4, configuration: { name: "Second account", provider: "openai-v1", model: "model-b", region: "provider-managed", currency: "USD", input_price_per_million: 2000000, output_price_per_million: 5000000 } },
  ] }],
} }) }));

describe("model source choices", () => {
  it("adds a second account with its current revision while preserving the first weight", () => {
    const change = vi.fn();
    render(<ModelSourcePicker scenario="synthetic" workspace="workspace-one" value={{ aliases: [{ logical_alias: "coding-main", sources: [{ source_id: "one", revision: 2, weight: 3 }] }] }} onChange={change} />);
    fireEvent.click(screen.getByRole("checkbox", { name: /Second account/ }));
    expect(change).toHaveBeenCalledWith({ aliases: [{ logical_alias: "coding-main", sources: [
      { source_id: "one", revision: 2, weight: 3 }, { source_id: "two", revision: 4, weight: 1 },
    ] }] });
    expect(screen.getByText(/Weights distribute new allocations/)).toBeInTheDocument();
  });
});
