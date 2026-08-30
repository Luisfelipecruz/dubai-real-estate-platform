/**
 * Tests for the run metadata strip.
 *
 * Both assertions guard plan §11.4.3 and §11.5: never publish a latency without saying
 * it came from one machine, and never hide which model answered.
 */
import { render, screen } from "@testing-library/react";
import { RunMeta } from "./RunMeta";

describe("RunMeta", () => {
  it("never shows a latency without the one-machine caveat", () => {
    // M-21, M-35, M-48 and M-55 all recorded this independently, and M-55 measured a
    // 3–4× swing on host load ALONE. A number on screen without that context invites
    // exactly the comparison those four measurements forbid.
    render(
      <RunMeta
        provider="local"
        model="gpt-oss:20b"
        timings={[{ label: "total", ms: 65956 }]}
      />,
    );

    const caveat = screen.getByTestId("latency-caveat");
    expect(caveat).toHaveTextContent(/one developer laptop/i);
    expect(caveat).toHaveTextContent(/3–4×/);
  });

  it("names the provider and model that answered", () => {
    // `local · gpt-oss:20b` is a more interesting badge than a hidden one, and hiding it
    // is how a demo takes credit for a frontier model it is not running.
    render(
      <RunMeta provider="local" model="gpt-oss:20b" timings={[]} />,
    );
    expect(screen.getByTestId("run-model")).toHaveTextContent("local · gpt-oss:20b");
  });

  it("renders a long run in seconds", () => {
    render(
      <RunMeta
        provider="local"
        model="gpt-oss:20b"
        timings={[{ label: "total", ms: 65956 }]}
      />,
    );
    expect(screen.getByText("66.0 s")).toBeInTheDocument();
  });

  it("keeps an unpriced cost distinct from a free one", () => {
    const { rerender } = render(
      <RunMeta provider="local" model="m" timings={[]} cost={0} costPriced />,
    );
    expect(screen.getByText("$0.00")).toBeInTheDocument();

    rerender(
      <RunMeta provider="anthropic" model="m" timings={[]} cost={0} costPriced={false} />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
