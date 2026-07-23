import { describe, expect, it } from "vitest";
import { nextDeletePrompt, pruneDismissed } from "./deletePromptQueue";

interface Item { id: string; }
const idOf = (i: Item) => i.id;

describe("nextDeletePrompt", () => {
  it("returns null when there are no held prompts", () => {
    expect(nextDeletePrompt<Item>([], idOf, new Set())).toBeNull();
  });

  it("returns the first item when nothing is dismissed", () => {
    const items: Item[] = [{ id: "a" }, { id: "b" }];
    expect(nextDeletePrompt(items, idOf, new Set())).toEqual({ id: "a" });
  });

  it("skips a dismissed item and surfaces the next one — queueing multiple pending items", () => {
    const items: Item[] = [{ id: "a" }, { id: "b" }, { id: "c" }];
    expect(nextDeletePrompt(items, idOf, new Set(["a"]))).toEqual({ id: "b" });
  });

  it("returns null once every held prompt has been dismissed this session (none resolved)", () => {
    const items: Item[] = [{ id: "a" }, { id: "b" }];
    expect(nextDeletePrompt(items, idOf, new Set(["a", "b"]))).toBeNull();
  });
});

describe("pruneDismissed", () => {
  it("drops a dismissed id no longer present in the live list (resolved meanwhile)", () => {
    const items: Item[] = [{ id: "b" }];
    const pruned = pruneDismissed(items, idOf, new Set(["a", "b"]));
    expect(pruned).toEqual(new Set(["b"]));
  });

  it("keeps every dismissed id still present", () => {
    const items: Item[] = [{ id: "a" }, { id: "b" }];
    const pruned = pruneDismissed(items, idOf, new Set(["a", "b"]));
    expect(pruned).toEqual(new Set(["a", "b"]));
  });

  it("returns an empty set when nothing was dismissed", () => {
    expect(pruneDismissed<Item>([{ id: "a" }], idOf, new Set())).toEqual(new Set());
  });
});
