/**
 * Test environment setup — added by m18.
 *
 * The polyfills below are not boilerplate. jsdom does not implement the streaming half
 * of the Fetch API, and the SSE client in `src/lib/stream.ts` is built on exactly that:
 * `response.body` as a ReadableStream, decoded incrementally with a TextDecoder. Without
 * these, the tests that matter most for this milestone — a frame split across chunk
 * boundaries, a stream that ends mid-run — could not be written at all, and the client
 * would ship with only its pure parser covered.
 *
 * They are taken from Node's own implementations rather than from a shim package: the
 * browser runs the real thing, and a hand-written fake would be testing the fake.
 */
import "@testing-library/jest-dom";
import { TextDecoder, TextEncoder } from "node:util";
import { ReadableStream, TransformStream, WritableStream } from "node:stream/web";

const g = globalThis as unknown as Record<string, unknown>;

if (typeof g.TextEncoder === "undefined") g.TextEncoder = TextEncoder;
if (typeof g.TextDecoder === "undefined") g.TextDecoder = TextDecoder;
if (typeof g.ReadableStream === "undefined") g.ReadableStream = ReadableStream;
if (typeof g.WritableStream === "undefined") g.WritableStream = WritableStream;
if (typeof g.TransformStream === "undefined") g.TransformStream = TransformStream;
