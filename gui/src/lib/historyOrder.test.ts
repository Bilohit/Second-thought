import { describe, it, expect } from "vitest";
import { liveCategoryCounts } from "./historyOrder";

describe("liveCategoryCounts", () => {
  it("sorts by count desc and drops system (_) folders", () => {
    const rows = liveCategoryCounts([
      { name: "Tech", file_count: 2, path: "", description: null },
      { name: "_system", file_count: 9, path: "", description: null },
      { name: "Finance", file_count: 5, path: "", description: null },
    ]);
    expect(rows.map((r) => r.category)).toEqual(["Finance", "Tech"]);
  });
});
