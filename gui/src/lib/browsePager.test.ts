import { describe, it, expect } from "vitest";
import { chunkProjects, browsePagerInfo, PROJECTS_PER_PAGE } from "./browsePager";

describe("chunkProjects", () => {
  it("splits an exact multiple of the page size into full pages", () => {
    const items = Array.from({ length: 16 }, (_, i) => i);
    const pages = chunkProjects(items, 8);
    expect(pages.length).toBe(2);
    expect(pages[0]).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    expect(pages[1]).toEqual([8, 9, 10, 11, 12, 13, 14, 15]);
  });

  it("gives the last page fewer items for a partial remainder", () => {
    const items = Array.from({ length: 9 }, (_, i) => i);
    const pages = chunkProjects(items, 8);
    expect(pages.length).toBe(2);
    expect(pages[0].length).toBe(8);
    expect(pages[1]).toEqual([8]);
  });

  it("produces zero pages for zero items", () => {
    expect(chunkProjects([], 8)).toEqual([]);
  });

  it("defaults to the 8-per-page (4x2) constant", () => {
    expect(PROJECTS_PER_PAGE).toBe(8);
    const items = Array.from({ length: PROJECTS_PER_PAGE }, (_, i) => i);
    expect(chunkProjects(items).length).toBe(1);
  });
});

describe("browsePagerInfo", () => {
  it("reports one page, both arrows disabled, for zero projects", () => {
    const info = browsePagerInfo(0, 1, 8);
    expect(info.pageCount).toBe(1);
    expect(info.page).toBe(1);
    expect(info.canPrev).toBe(false);
    expect(info.canNext).toBe(false);
  });

  it("enables next but not prev on the first of several pages", () => {
    const info = browsePagerInfo(20, 1, 8); // 3 pages
    expect(info.pageCount).toBe(3);
    expect(info.canPrev).toBe(false);
    expect(info.canNext).toBe(true);
  });

  it("enables prev but not next on the last page", () => {
    const info = browsePagerInfo(20, 3, 8);
    expect(info.pageCount).toBe(3);
    expect(info.page).toBe(3);
    expect(info.canPrev).toBe(true);
    expect(info.canNext).toBe(false);
  });

  it("clamps a requested page above the last page down to the last page", () => {
    const info = browsePagerInfo(9, 99, 8); // 2 pages
    expect(info.pageCount).toBe(2);
    expect(info.page).toBe(2);
    expect(info.canNext).toBe(false);
  });

  it("clamps a requested page below 1 up to 1", () => {
    const info = browsePagerInfo(20, 0, 8);
    expect(info.page).toBe(1);
    expect(info.canPrev).toBe(false);
  });

  it("handles an exact multiple of the page size (16 items, 8/page = 2 pages)", () => {
    const info = browsePagerInfo(16, 2, 8);
    expect(info.pageCount).toBe(2);
    expect(info.page).toBe(2);
    expect(info.canNext).toBe(false);
    expect(info.canPrev).toBe(true);
  });

  it("handles a partial last page (9 items, 8/page = 2 pages, second page has 1)", () => {
    const info = browsePagerInfo(9, 2, 8);
    expect(info.pageCount).toBe(2);
    expect(info.canNext).toBe(false);
  });
});
