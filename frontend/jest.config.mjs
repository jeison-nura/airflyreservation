import nextJest from "next/jest.js";

export default nextJest({ dir: "./" })({
  testEnvironment: "node",
  injectGlobals: false,
  roots: ["<rootDir>/src"],
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" },
  coverageProvider: "v8",
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/types.ts",
    "!src/**/*.test.{ts,tsx}",
  ],
  coverageReporters: ["text", "html", "lcov", "json-summary"],
  coverageThreshold: { global: { lines: 80 } },
});
