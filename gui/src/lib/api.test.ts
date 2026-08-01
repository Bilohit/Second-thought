import { describe, it, expect, vi, beforeEach } from "vitest";

// api.ts pulls in the Tauri secret + opener plugins at module load time even
// though these tests never touch a real window -- mirrors logger.test.ts's
// mock of @tauri-apps/api/core.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue("test-secret"),
}));
vi.mock("@tauri-apps/plugin-opener", () => ({
  openPath: vi.fn(),
  revealItemInDir: vi.fn(),
}));

import { listProjects, notesForProject, notesForTag } from "./api";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

describe("listProjects", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("requests GET /vault/projects", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      jsonResponse({
        projects: [
          {
            name: "acme",
            description: "d",
            renamed_from: null,
            created: "2026-01-01T00:00:00",
            modified: "2026-01-02T00:00:00",
            file_count: 3,
          },
        ],
        vault_root: "/vault",
      }),
    );

    const result = await listProjects();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:7070/vault/projects");
    expect(result.projects).toEqual([
      {
        name: "acme",
        description: "d",
        renamed_from: null,
        created: "2026-01-01T00:00:00",
        modified: "2026-01-02T00:00:00",
        file_count: 3,
      },
    ]);
    expect(result.vault_root).toBe("/vault");
  });

  it("rejects via the existing error path on a non-OK response", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ detail: "boom" }, false, 500));

    await expect(listProjects()).rejects.toThrow("boom");
  });

  it("falls back to the assertOk fallback message when the error body has no detail", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({}, false, 500));

    await expect(listProjects()).rejects.toThrow("Failed to list projects");
  });
});

describe("notesForProject", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("requests GET /search?project=<name> with the explicit 200 default limit", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForProject("acme");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/search");
    expect(parsed.searchParams.get("project")).toBe("acme");
    expect(parsed.searchParams.get("limit")).toBe("200");
  });

  it("encodes a project name containing reserved URL characters", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForProject("R&D / 2026?");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("project")).toBe("R&D / 2026?");
    expect(url as string).not.toContain("R&D / 2026?");
  });

  it("lets a caller override the default limit", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForProject("acme", { limit: 50 });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("limit")).toBe("50");
  });

  it("returns the SearchResult rows, including modified", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      jsonResponse({
        results: [
          { project: "acme", path: "acme/note.md", filename: "note.md", modified: 1234.5 },
        ],
      }),
    );

    const results = await notesForProject("acme");
    expect(results).toEqual([
      { project: "acme", path: "acme/note.md", filename: "note.md", modified: 1234.5 },
    ]);
  });

  it("rejects via the existing search error path on a non-OK response", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({}, false, 500));

    await expect(notesForProject("acme")).rejects.toThrow("Search failed");
  });
});

describe("notesForTag", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("requests GET /search?q=tag:<name> with the explicit 200 default limit", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForTag("project-idea");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe("/search");
    expect(parsed.searchParams.get("q")).toBe("tag:project-idea");
    expect(parsed.searchParams.get("limit")).toBe("200");
  });

  it("encodes a tag name containing reserved URL characters", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForTag("needs review?");

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("q")).toBe("tag:needs review?");
    expect(url as string).not.toContain("needs review?");
  });

  it("lets a caller override the default limit", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));

    await notesForTag("project-idea", { limit: 10 });

    const [url] = fetchMock.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get("limit")).toBe("10");
  });

  it("rejects via the existing search error path on a non-OK response", async () => {
    const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse({}, false, 500));

    await expect(notesForTag("project-idea")).rejects.toThrow("Search failed");
  });
});
