/**
 * Tests for the answer panel.
 *
 * These are the highest-value tests in the milestone, because they encode judgements the
 * project spent four milestones establishing and which a later, well-meaning styling
 * pass would otherwise undo. "Make the refusal red so it stands out" is a reasonable
 * thing for someone to say; it is also wrong, and this file is where it fails.
 */
import { render, screen } from "@testing-library/react";
import { AnswerPanel } from "./AnswerPanel";

describe("a refusal", () => {
  it("renders as a neutral, explained outcome and NOT as an error", () => {
    // Plan §11.4.1. `/agent/query` returns HTTP 200 here. On the golden set a refusal is
    // the CORRECT answer for exactly the questions m13a proved unanswerable, and M-17
    // measured that the system refused on those and only those.
    render(<AnswerPanel outcome="refused" answer="I can't provide that information." />);

    expect(screen.getByTestId("refusal-notice")).toBeInTheDocument();
    expect(screen.getByTestId("outcome-badge")).toHaveTextContent("refused");
    // The destructive variant is reserved for `failed`, the one outcome that is an error.
    expect(screen.getByTestId("outcome-badge").className).not.toMatch(/destructive/);
  });

  it("explains itself in words, so the reader does not need the docs", () => {
    render(<AnswerPanel outcome="refused" answer={null} />);
    expect(screen.getByTestId("refusal-notice")).toHaveTextContent(/HTTP 200/);
  });

  it("prefers the API's own unanswerable_reason when there is one", () => {
    render(
      <AnswerPanel
        outcome="refused"
        answer={null}
        unanswerableReason="The corpus contains no rent data for Reykjavik."
      />,
    );
    expect(screen.getByTestId("refusal-notice")).toHaveTextContent("Reykjavik");
  });
});

describe("the empty answer", () => {
  it("is named as a known defect rather than left blank", () => {
    // M-47, reproduced live while this component was written: a 66.0-second run returned
    // `outcome: answered`, `answered: true` and an empty string. A blank card would be
    // indistinguishable from a loading state, so the one defect the milestone knows
    // about would be the single thing the UI hid.
    render(<AnswerPanel outcome="answered" answer="" />);

    const defect = screen.getByTestId("empty-answer-defect");
    expect(defect).toBeInTheDocument();
    expect(defect).toHaveTextContent(/known defect/i);
    expect(screen.queryByTestId("answer-body")).not.toBeInTheDocument();
  });

  it("treats whitespace-only as empty", () => {
    // Braces, not quotes. In a JSX string attribute `"\n"` is a literal backslash
    // followed by an `n` — two visible characters — so the quoted form tests the
    // opposite of what it appears to.
    render(<AnswerPanel outcome="answered" answer={"   \n  "} />);
    expect(screen.getByTestId("empty-answer-defect")).toBeInTheDocument();
  });

  it("does not fire on a real answer", () => {
    render(<AnswerPanel outcome="answered" answer="Dubai Marina, with 4,812." />);
    expect(screen.queryByTestId("empty-answer-defect")).not.toBeInTheDocument();
    expect(screen.getByTestId("answer-body")).toHaveTextContent("4,812");
  });

  it("does not fire on a refusal, which is empty for a different reason", () => {
    render(<AnswerPanel outcome="refused" answer="" />);
    expect(screen.queryByTestId("empty-answer-defect")).not.toBeInTheDocument();
    expect(screen.getByTestId("refusal-notice")).toBeInTheDocument();
  });
});

describe("the step cap", () => {
  it("says the findings are partial", () => {
    render(<AnswerPanel outcome="max_steps" answer={null} />);
    expect(screen.getByTestId("cap-notice")).toHaveTextContent(/partial/i);
  });
});

describe("grounding warnings", () => {
  it("shows every warning rather than hiding them", () => {
    // Suppressing these to make an answer look clean would delete the feature in order
    // to flatter the demo — the move m13a refused when it kept a decoy in the corpus
    // rather than patching the metric around it.
    render(
      <AnswerPanel
        outcome="answered"
        answer="4,812 transactions."
        warnings={[
          "the step cap (2) was reached before the model produced an answer.",
          "2 numbers in the answer appear in no tool result.",
        ]}
      />,
    );

    const warnings = screen.getByTestId("grounding-warnings");
    expect(warnings).toHaveTextContent("Grounding warnings (2)");
    expect(warnings).toHaveTextContent(/appear in no tool result/);
  });

  it("renders nothing when the answer is clean", () => {
    render(<AnswerPanel outcome="answered" answer="fine" warnings={[]} />);
    expect(screen.queryByTestId("grounding-warnings")).not.toBeInTheDocument();
  });
});

describe("routing categories", () => {
  it("renders the list /agent/query returns", () => {
    render(
      <AnswerPanel outcome="answered" answer="ok" categories={["meta", "geo", "sql"]} />,
    );
    expect(screen.getAllByTestId("category-chip")).toHaveLength(3);
  });

  it("survives the null a tool-less run returns", () => {
    render(<AnswerPanel outcome="refused" answer="" categories={null} />);
    expect(screen.getByText("no tools called")).toBeInTheDocument();
  });
});
