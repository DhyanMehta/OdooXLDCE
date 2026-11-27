import assert from "node:assert/strict";
import { test } from "node:test";
import { prettyRoleCode } from "../src/lib/roles.ts";

test("renders readable role labels in admin lists", () => {
  assert.equal(prettyRoleCode("event_organizer"), "event organizer");
  assert.equal(prettyRoleCode("  membership__manager  "), "membership manager");
  assert.equal(prettyRoleCode("club_\t officer"), "club officer");
  assert.equal(prettyRoleCode("Club Admin"), "Club Admin");
});

test("uses the missing-role placeholder for empty labels", () => {
  for (const code of [null, undefined, "", "   ", "__"]) {
    assert.equal(prettyRoleCode(code), "—");
  }
});
