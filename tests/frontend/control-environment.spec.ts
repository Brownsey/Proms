import { expect, test } from "@playwright/test";

import { controlRouteAvailable, resolveApiUrl } from "../../app/control/environment";

test("hides local control on Vercel only", () => {
  expect(controlRouteAvailable("1")).toBe(false);
  expect(controlRouteAvailable(undefined)).toBe(true);
});

test("uses same-origin in production", () => {
  expect(resolveApiUrl("production", "http://127.0.0.1:8123")).toBe("");
});

test("allows only loopback development API overrides", () => {
  expect(resolveApiUrl("development", "http://127.0.0.1:8123/path")).toBe("http://127.0.0.1:8123");
  expect(resolveApiUrl("development", "https://localhost:8123")).toBe("https://localhost:8123");
  expect(resolveApiUrl("development", "https://example.com")).toBe("");
  expect(resolveApiUrl("development", "not a URL")).toBe("");
});
