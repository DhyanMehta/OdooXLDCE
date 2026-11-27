import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatCountdown, statusBadgeClass } from "../src/lib/format.ts";

const expiresAt = "2026-10-01T12:00:00.000Z";
const deadline = Date.parse(expiresAt);

describe("pending order countdown", () => {
  it("shows one second throughout the final fraction of a second", () => {
    for (const remaining of [1000, 500, 1]) {
      assert.equal(formatCountdown(expiresAt, deadline - remaining), "0m 01s");
    }
  });

  it("expires at the deadline and stays expired afterwards", () => {
    assert.equal(formatCountdown(expiresAt, deadline), "Expired");
    assert.equal(formatCountdown(expiresAt, deadline + 1), "Expired");
  });

  it("carries seconds into the next minute or hour", () => {
    const cases = [
      [59_000, "0m 59s"],
      [59_001, "1m 00s"],
      [60_001, "1m 01s"],
      [3_599_000, "59m 59s"],
      [3_599_001, "1h 0m 00s"],
      [3_661_000, "1h 1m 01s"],
    ];
    for (const [remaining, expected] of cases) {
      assert.equal(formatCountdown(expiresAt, deadline - remaining), expected);
    }
  });

  it("shows no countdown for a missing expiry or invalid clock", () => {
    for (const input of [null, undefined, "", "invalid"]) {
      assert.equal(formatCountdown(input, deadline), null);
    }
    for (const now of [NaN, Infinity, -Infinity]) {
      assert.equal(formatCountdown(expiresAt, now), null);
    }
  });
});

describe("status badge classes", () => {
  it("recognizes warning and danger statuses with incidental whitespace", () => {
    assert.equal(statusBadgeClass(" Pending "), "badge badge--warn");
    assert.equal(statusBadgeClass("\tREFUND_REQUIRED"), "badge badge--warn");
    assert.equal(statusBadgeClass("Expired\n"), "badge badge--danger");
  });

  it("retains the default styling for ordinary, unknown and empty statuses", () => {
    for (const status of ["paid", "confirmed", "new_state", "", "   "]) {
      assert.equal(statusBadgeClass(status), "badge");
    }
  });
});
