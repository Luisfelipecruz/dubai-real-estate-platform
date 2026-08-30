/**
 * Tests for the citation list.
 *
 * The distinction under test — resolved vs. quote_found — is the reason `/ask` is
 * different from a RAG demo. m14 found both failures in real answers, and a UI that
 * collapsed them into one "verified" badge would throw away the finding.
 */
import { render, screen } from "@testing-library/react";
import { CitationList } from "./CitationList";
import type { ResolvedCitation } from "@/lib/copilot";

function citation(overrides: Partial<ResolvedCitation> = {}): ResolvedCitation {
  return {
    chunk_id: 586,
    quote: "Reciprocal Rank Fusion over the ranks of each arm",
    resolved: true,
    quote_found: true,
    source_type: "doc",
    source_id: "docs/rag-corpus-design.md",
    heading_path: "Hybrid retrieval > Fusion",
    ...overrides,
  };
}

describe("a verified citation", () => {
  it("is badged verified", () => {
    render(<CitationList citations={[citation()]} />);
    expect(screen.getByTestId("citation-verified")).toBeInTheDocument();
    expect(screen.queryByTestId("citation-unverified")).not.toBeInTheDocument();
  });

  it("counts how many of the total were verified", () => {
    render(
      <CitationList
        citations={[citation(), citation({ quote_found: false }), citation()]}
      />,
    );
    expect(screen.getByText(/2 of 3 citations verified/)).toBeInTheDocument();
  });
});

describe("a quote that is not in the chunk", () => {
  it("is flagged as a paraphrase presented as a quotation", () => {
    // The common failure and the easy one to miss: the chunk is real and was retrieved,
    // but these words are not in it. m14 caught a quote that reversed a measurement AND
    // the conclusion drawn from it this way.
    render(<CitationList citations={[citation({ quote_found: false })]} />);

    expect(screen.getByTestId("citation-unverified")).toHaveTextContent(
      /quote not found/i,
    );
    expect(screen.getByTestId("citation")).toHaveTextContent(/paraphrase/i);
  });
});

describe("a chunk that was never retrieved", () => {
  it("is flagged as an invented source, distinctly from a bad quote", () => {
    render(
      <CitationList citations={[citation({ resolved: false, quote_found: false })]} />,
    );
    expect(screen.getByTestId("citation-unverified")).toHaveTextContent(
      /source not retrieved/i,
    );
    expect(screen.getByTestId("citation")).toHaveTextContent(/invented/i);
  });

  it("does not also claim the quote was checked", () => {
    // An unresolved chunk cannot have had its quote checked — there was nothing to check
    // it against. Showing both badges would assert a check that never ran.
    render(
      <CitationList citations={[citation({ resolved: false, quote_found: false })]} />,
    );
    expect(screen.getAllByTestId("citation-unverified")).toHaveLength(1);
  });
});

describe("no citations", () => {
  it("explains that this is correct for a refusal", () => {
    render(<CitationList citations={[]} />);
    expect(screen.getByText(/correct for a refusal/i)).toBeInTheDocument();
  });
});
