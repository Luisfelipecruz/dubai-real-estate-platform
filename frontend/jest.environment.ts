/**
 * A jsdom environment with the Fetch API put back.
 *
 * jsdom does not implement `fetch`, `Response`, `Request` or `Headers`, and Jest builds
 * the jsdom global from scratch rather than inheriting Node's — so inside a test they are
 * simply undefined, even on Node 22 where they exist everywhere else.
 *
 * This file is the fix because of WHERE it runs. A test environment module is loaded by
 * Jest in the Node realm, outside the sandbox it is about to construct, so the bare
 * identifiers below resolve to Node's real undici-backed implementations. The same
 * assignment written inside `jest.setup.ts` cannot work: that file already runs inside
 * the jsdom context, where there is nothing to copy from.
 *
 * Node's own implementations are used rather than a stub because `src/lib/stream.ts`
 * reads `response.body` as a real ReadableStream, and a hand-written fake would be
 * testing the fake.
 */
import JSDOMEnvironment from "jest-environment-jsdom";
import type { EnvironmentContext, JestEnvironmentConfig } from "@jest/environment";

export default class FetchCapableJSDOMEnvironment extends JSDOMEnvironment {
  constructor(config: JestEnvironmentConfig, context: EnvironmentContext) {
    super(config, context);

    const inherit = {
      fetch,
      Response,
      Request,
      Headers,
      FormData,
      ReadableStream,
      WritableStream,
      TransformStream,
      TextEncoder,
      TextDecoder,
      structuredClone,
    } as const;

    for (const [name, impl] of Object.entries(inherit)) {
      if (typeof (this.global as Record<string, unknown>)[name] === "undefined") {
        (this.global as Record<string, unknown>)[name] = impl;
      }
    }
  }
}
