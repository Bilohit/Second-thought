// TagsView.test.ts — ISS-019: machine-written failure tags (namespaced
// "sys/..." at the write site in omni_capture/scratchpad.py) must never
// appear in the Tags browser's tree, whether namespaced (fresh vaults) or
// bare (existing vaults that already have unnamespaced notes on disk).
import { describe, expect, it } from "vitest";
import { filterMachineTags, isMachineTag, splitProjects } from "./TagsView";
import type { TagNode } from "../../lib/api";

describe("isMachineTag", () => {
  it("flags the sys/ namespace node and its members", () => {
    expect(isMachineTag("sys/")).toBe(true);
    expect(isMachineTag("sys")).toBe(true);
    expect(isMachineTag("sys/llm-failed")).toBe(true);
    expect(isMachineTag("sys/vision-failed")).toBe(true);
  });

  it("flags known bare legacy machine tags for existing vaults", () => {
    expect(isMachineTag("llm-failed")).toBe(true);
    expect(isMachineTag("vision-failed")).toBe(true);
    expect(isMachineTag("transcription_failure")).toBe(true);
    expect(isMachineTag("whisper_model_error")).toBe(true);
    expect(isMachineTag("winerror_2")).toBe(true);
  });

  it("never flags ordinary user content tags", () => {
    expect(isMachineTag("project")).toBe(false);
    expect(isMachineTag("project/alpha")).toBe(false);
    expect(isMachineTag("reading")).toBe(false);
    expect(isMachineTag("systems-design")).toBe(false); // starts with "system", not "sys/"
  });
});

describe("filterMachineTags", () => {
  it("drops the whole sys/ namespace node, including its children", () => {
    const tags: TagNode[] = [
      {
        tag: "sys/", count: 2, recent: [],
        children: [
          { tag: "sys/llm-failed", count: 1, recent: [], children: [] },
          { tag: "sys/vision-failed", count: 1, recent: [], children: [] },
        ],
      },
      {
        tag: "project/", count: 2, recent: [],
        children: [{ tag: "project/alpha", count: 2, recent: [], children: [] }],
      },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const result = filterMachineTags(tags);

    expect(result.map((n) => n.tag)).toEqual(["project/", "reading"]);
  });

  it("drops bare legacy machine tags without touching sibling user tags", () => {
    const tags: TagNode[] = [
      { tag: "llm-failed", count: 1, recent: [], children: [] },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const result = filterMachineTags(tags);

    expect(result.map((n) => n.tag)).toEqual(["reading"]);
  });
});

describe("splitProjects", () => {
  it("extracts project/ leaf children with full tag values and counts", () => {
    const tags: TagNode[] = [
      {
        tag: "project/", count: 3, recent: [],
        children: [
          { tag: "project/alpha", count: 2, recent: [], children: [] },
          { tag: "project/beta", count: 1, recent: [], children: [] },
        ],
      },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const { projects } = splitProjects(tags);

    expect(projects).toEqual([
      { tag: "project/alpha", count: 2, recent: [], children: [] },
      { tag: "project/beta", count: 1, recent: [], children: [] },
    ]);
  });

  it("removes the project/ node from rest without touching sibling tags", () => {
    const tags: TagNode[] = [
      {
        tag: "project/", count: 3, recent: [],
        children: [{ tag: "project/alpha", count: 2, recent: [], children: [] }],
      },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const { rest } = splitProjects(tags);

    expect(rest.map((n) => n.tag)).toEqual(["reading"]);
  });

  it("handles a bare 'project' namespace node (trailing slash optional)", () => {
    const tags: TagNode[] = [
      {
        tag: "project", count: 1, recent: [],
        children: [{ tag: "project/alpha", count: 1, recent: [], children: [] }],
      },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const { projects, rest } = splitProjects(tags);

    expect(projects).toEqual([{ tag: "project/alpha", count: 1, recent: [], children: [] }]);
    expect(rest.map((n) => n.tag)).toEqual(["reading"]);
  });

  it("returns no projects when there's no project/ namespace node", () => {
    const tags: TagNode[] = [
      { tag: "reading", count: 3, recent: [], children: [] },
      { tag: "systems-design", count: 1, recent: [], children: [] },
    ];

    const { projects, rest } = splitProjects(tags);

    expect(projects).toEqual([]);
    expect(rest).toEqual(tags);
  });

  it("keeps a bare top-level 'project' node with no children in rest (ordinary user tag)", () => {
    const tags: TagNode[] = [
      { tag: "project", count: 0, recent: [], children: [] },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const { projects, rest } = splitProjects(tags);

    expect(projects).toEqual([]);
    expect(rest.map((n) => n.tag)).toEqual(["project", "reading"]);
  });

  it("composes with filterMachineTags: sys/ still dropped, project/ leaves preserved", () => {
    const tags: TagNode[] = [
      {
        tag: "sys/", count: 2, recent: [],
        children: [{ tag: "sys/llm-failed", count: 1, recent: [], children: [] }],
      },
      {
        tag: "project/", count: 1, recent: [],
        children: [{ tag: "project/alpha", count: 1, recent: [], children: [] }],
      },
      { tag: "reading", count: 3, recent: [], children: [] },
    ];

    const { projects, rest } = splitProjects(filterMachineTags(tags));

    expect(projects).toEqual([{ tag: "project/alpha", count: 1, recent: [], children: [] }]);
    expect(rest.map((n) => n.tag)).toEqual(["reading"]);
  });
});
