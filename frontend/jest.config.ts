/**
 * Jest configuration — added by m18.
 *
 * The frontend had NO test setup at all before this milestone: no Jest, no React
 * Testing Library, nothing in devDependencies, while the root CLAUDE.md requires both.
 * That is why the infrastructure is a scope item in the plan (§11.6) rather than a
 * footnote — there was nothing to add tests to.
 *
 * `next/jest` is used rather than a hand-rolled SWC/babel transform because it reads
 * next.config.ts, tsconfig paths and the CSS/asset stubs from the framework itself.
 * A bespoke transform here would drift from the build the moment Next changes.
 */
import type { Config } from "jest";
import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

const config: Config = {
  coverageProvider: "v8",
  // Not the bare "jsdom": jsdom has no fetch, no Response and no ReadableStream, and the
  // SSE client is built on all three. See jest.environment.ts for why the polyfill has
  // to live in an environment rather than in the setup file.
  testEnvironment: "<rootDir>/jest.environment.ts",
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  // next/jest derives this from tsconfig paths, but stating it keeps the mapping
  // readable next to the tests that rely on it.
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  testPathIgnorePatterns: ["<rootDir>/node_modules/", "<rootDir>/.next/"],
  collectCoverageFrom: [
    "src/lib/**/*.{ts,tsx}",
    "src/components/copilot/**/*.{ts,tsx}",
  ],
};

export default createJestConfig(config);
