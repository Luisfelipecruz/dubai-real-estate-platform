/**
 * Tests for the in-flight state.
 *
 * The point of this component is that it does NOT fake streaming, so the test that
 * matters most is the one asserting it says so out loud.
 */
import { render, screen } from "@testing-library/react";
import { RunProgress } from "./RunProgress";

describe("RunProgress", () => {
  it("says plainly that there is no live trace when streaming is unavailable", () => {
    // A typewriter animation over a response that arrived in one chunk is a lie about
    // latency, and this project's whole thesis is honest measurement. The degraded state
    // is described instead of disguised.
    render(<RunProgress streaming={false} stepsSoFar={0} />);

    const notice = screen.getByTestId("no-streaming-notice");
    expect(notice).toHaveTextContent(/No live trace/);
    expect(notice).toHaveTextContent(/agent\/stream/);
  });

  it("quotes the real observed range rather than a guess", () => {
    // 1.4 s to 66.0 s, both measured on this machine. A progress indicator that implies
    // a few seconds in front of a run that can take over a minute is the bug report the
    // plan warns about.
    render(<RunProgress streaming={false} stepsSoFar={0} />);
    expect(screen.getByTestId("no-streaming-notice")).toHaveTextContent(/66\.0 seconds/);
  });

  it("reports live step counts once streaming is available", () => {
    render(<RunProgress streaming stepsSoFar={3} />);
    expect(screen.queryByTestId("no-streaming-notice")).not.toBeInTheDocument();
    expect(screen.getByText(/3 steps so far/)).toBeInTheDocument();
  });

  it("gets the singular right at one step", () => {
    render(<RunProgress streaming stepsSoFar={1} />);
    expect(screen.getByText(/1 step so far/)).toBeInTheDocument();
  });

  it("shows an elapsed counter, because the wait is the thing being managed", () => {
    render(<RunProgress streaming={false} stepsSoFar={0} />);
    expect(screen.getByTestId("run-progress")).toHaveTextContent(/0\.0s elapsed/);
  });
});
