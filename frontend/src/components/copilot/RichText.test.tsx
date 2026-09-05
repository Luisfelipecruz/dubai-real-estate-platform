import { render, screen } from "@testing-library/react";
import { RichText, parse } from "./RichText";

describe("RichText", () => {
  it("bolds the figure in the answer that started this", () => {
    render(<RichText text="There are **35,577** villa transactions recorded." />);
    // The asterisks must be gone from the text the reader sees.
    expect(screen.getByText(/villa transactions recorded/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("**");
    expect(screen.getByText("35,577").tagName).toBe("STRONG");
  });

  it("renders inline code", () => {
    render(<RichText text="The column is `annual_amount`." />);
    expect(screen.getByText("annual_amount").tagName).toBe("CODE");
  });

  it("leaves an unmatched marker as literal punctuation", () => {
    // The failure that matters: a greedy parser treats the opener as the start of a span
    // and swallows the remainder of the answer, so the reader loses the sentence.
    render(<RichText text="A 5 ** 2 expression, and then real prose." />);
    expect(document.body.textContent).toBe("A 5 ** 2 expression, and then real prose.");
  });

  it("leaves an empty span alone rather than emitting an empty element", () => {
    render(<RichText text="nothing **** here" />);
    expect(document.body.textContent).toBe("nothing **** here");
    expect(document.querySelector("strong")).toBeNull();
  });

  it("handles several spans in one string, in order", () => {
    const nodes = parse("**a** then `b` then **c**");
    expect(nodes).toHaveLength(5);
    expect(document.body.textContent).toBe("");
    render(<RichText text="**a** then `b` then **c**" />);
    expect(document.body.textContent).toBe("a then b then c");
  });

  it("never produces markup from link syntax", () => {
    // Model output is untrusted. This renders React nodes, never HTML, so the whole
    // class of injection is absent -- the link syntax simply stays as text.
    render(<RichText text="see [here](javascript:alert(1)) for more" />);
    expect(document.querySelector("a")).toBeNull();
    expect(document.body.textContent).toContain("javascript:alert(1)");
  });

  it("passes plain prose through untouched", () => {
    render(<RichText text="No emphasis at all." />);
    expect(document.body.textContent).toBe("No emphasis at all.");
  });
});
