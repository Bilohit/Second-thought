/**
 * ProjectsView.tsx — sub-project 3 Task 4/5/7: the full-window Projects
 * screen's container. Owns the listProjects()/getTagTree() fetches, the
 * selected project/loose bucket/tag, and the rail's projects|tags view
 * mode. Renders <ProjectsRail/> on the left (260px, spec §3) and
 * <ProjectsPane/> on the right (head, rename/delete, description editor,
 * notes-head count + sort instrument, note rows, delete-confirm strip; Task
 * 7 added the tag-head variant).
 *
 * Task 7 (spec §5) also owns: fetching + machine-tag-filtering (ISS-019,
 * lib/projectsView.ts's filterMachineTags, moved here from the doomed
 * TagsView.tsx) + flattening (flattenTagTree) the tag tree once per visible
 * mount, and auto-selecting the first tag whenever the toggle lands on
 * Tags with nothing selected yet (spec §5.2) — never leaving the pane dead.
 *
 * Task 8 owns wiring this component into LibraryView/FullWindow in place of
 * the current `vault` section — not built here.
 *
 * Board: gui/mocks/2026-08-01-projects-fullwindow-v3.html. Spec: docs/
 * superpowers/specs/2026-08-02-projects-s3-fullwindow-design.md.
 */
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import ProjectsRail, { LOOSE_PROJECT_ID, type RailMode } from "./ProjectsRail";
import ProjectsPane from "./ProjectsPane";
import { listProjects, getStats, getTagTree, type ProjectEntry } from "../../lib/api";
import { filterMachineTags, flattenTagTree, type FlatTag } from "../../lib/projectsView";

interface Props {
  visible: boolean;
  onOpenNote?: (path: string) => void;
}

export default function ProjectsView({ visible, onOpenNote }: Props) {
  const [mode, setMode] = useState<RailMode>("projects");
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  // Every tile's count (loose included, under LOOSE_PROJECT_ID) comes from
  // ONE map built off getStats().by_project — the index's project column
  // (index_writer.py `SELECT project, COUNT(*) ... GROUP BY project`),
  // derived from the body tag. NOT ProjectEntry.file_count, which is
  // vault_admin._project_file_count counting .md files in a directory — the
  // exact directory-derived count s127 ripped out of the index (board lines
  // 335/448). The pane's note list (Task 5, GET /search?project=<name>)
  // reads the same project column, so this is the one source that can never
  // disagree with it by construction (spec §5.6: never a count from one
  // source beside a list from another).
  const [projectCounts, setProjectCounts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // The flat, machine-tag-filtered tag list (spec §5) and the currently
  // selected tag's RAW value (trailing slash preserved for a namespace
  // parent — see lib/projectsView.ts's flattenTagTree).
  //
  // GET /tags and GET /search?q=tag:<x> agree on MEMBERSHIP, not necessarily
  // on cardinality. Both resolve which paths carry the tag from the same
  // vault file scan (vault_admin.py:722-733 -> tag_index.scan_tag_paths /
  // resolve_paths) — that's the invariant spec §5.6 and the /tags docstring
  // exist to guarantee, and neither surface here invents its own number.
  // But GET /search only returns captures.db ROWS whose path is in that
  // resolved set (index_writer.py:840-852's docstring, enforced at :856's
  // `resolve_paths` + the `path IN (...)` filter) — it does not synthesize a
  // row for a file the scan found but the DB hasn't indexed yet. A note
  // freshly saved by the editor, or just synced in from Drive, can carry
  // the tag on disk before its next index pass reaches it: the rail (file
  // scan) counts it, the pane's fetched rows (DB) don't yet, and the rail
  // reads one higher than the pane until that pass runs. No gui/ change
  // closes that gap — ProjectsPane.tsx deliberately shows rows.length (what
  // it actually holds), not the rail's number, which is the honest choice
  // spec §5.6 itself asks for ("derive the displayed count from the rows it
  // holds, never a count from one source beside a list from another").
  const [tags, setTags] = useState<FlatTag[]>([]);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  // Shared by first-load and the rename/delete refetch (spec: "the rail's
  // tiles and counts are stale" after either succeeds — refetch BOTH
  // listProjects() and getStats() rather than letting the two surfaces
  // disagree). `keepSelection` is false only on first load, where the
  // board's own default (§ below) should apply instead of preserving a
  // (nonexistent yet) prior selection.
  //
  // FR-05 fix: `opts.rename` lets a rename's new identity land in the SAME
  // setState batch as the refreshed `projects` array, instead of the old
  // onRenamed handler calling setSelectedId(newName) synchronously and
  // refresh() separately — which left selectedId pointing at newName for
  // one or more renders while `projects` still only had the pre-refresh
  // (oldName) entry, so ProjectsPane's `selected` lookup came back null and
  // its description effect (deliberately keyed on [selectedId, mode], never
  // on [projects]/[selected] — see that effect's comment — to avoid
  // clobbering an in-progress edit on every unrelated refetch) synced
  // descDraft to "" and never re-ran once the real data landed. Resolving
  // the rename inside this same .then, against the freshest `prev` (via the
  // functional updater), means selectedId only ever flips to newName in the
  // exact render where `projects` already contains it — no null tick, and
  // the anti-clobber property is untouched because the effect's deps are
  // unchanged.
  const refresh = useCallback((opts?: { rename?: { oldName: string; newName: string } }) => {
    let cancelled = false;

    listProjects().then(({ projects: rows }) => {
      if (cancelled) return;
      setProjects(rows);
      setSelectedId((prev) => {
        // A rename of the CURRENTLY selected project: move the selection to
        // its new name in lockstep with the `projects` update above. If the
        // user has since selected something else, leave that alone —
        // renaming never steals a selection out from under a later click.
        if (opts?.rename && prev === opts.rename.oldName) return opts.rename.newName;
        // First open only (never overwrites a live selection): the first
        // project, or the loose bucket when the vault has none yet. Inferred
        // from the board's own mount() default (`sel: empty ? "__loose" :
        // "research"`) — the spec does not state an explicit rule for the
        // Projects half the way §5.2 does for Tags ("switching to Tags
        // selects the first tag"), so this is a judgment call, not a spec'd
        // behavior. Flagged in this task's report.
        return prev ?? (rows[0]?.name ?? LOOSE_PROJECT_ID);
      });
    }).catch(() => { if (!cancelled) setProjects([]); });

    getStats().then((stats) => {
      if (cancelled) return;
      const counts: Record<string, number> = {};
      for (const row of stats.by_project) counts[row.project] = row.count;
      // A registered project with zero captures simply has no row here —
      // ProjectsRail's `projectCounts[p.name] ?? 0` renders "0 notes" for
      // it, never "undefined notes" and never a vanished tile.
      setProjectCounts(counts);
    }).catch(() => { if (!cancelled) setProjectCounts({}); });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!visible) return;
    return refresh();
  }, [visible, refresh]);

  // Tag list: fetched once per visible mount, filtered (ISS-019) then
  // flattened before it ever reaches ProjectsRail — the rail renders what
  // it is given, it does not know about the tree shape or the machine-tag
  // filter (spec's trap 1).
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    getTagTree().then((r) => {
      if (cancelled) return;
      setTags(flattenTagTree(filterMachineTags(r.tags)));
    }).catch(() => { if (!cancelled) setTags([]); });
    return () => { cancelled = true; };
  }, [visible]);

  // Switching to Tags (or the tag list finishing its fetch while already on
  // Tags) auto-selects the first tag (spec §5.2) — flipping the toggle must
  // never hand back a dead right-hand pane that needs a second click before
  // the screen says anything. Never overwrites a live selection.
  useEffect(() => {
    if (mode === "tags" && !selectedTag && tags.length > 0) {
      setSelectedTag(tags[0].tag);
    }
  }, [mode, tags, selectedTag]);

  if (!visible) return null;

  return (
    <div style={containerStyle}>
      <ProjectsRail
        mode={mode}
        onModeChange={setMode}
        projects={projects}
        projectCounts={projectCounts}
        looseCount={projectCounts[LOOSE_PROJECT_ID] ?? 0}
        selectedId={selectedId}
        onSelect={setSelectedId}
        tags={tags}
        selectedTag={selectedTag}
        onSelectTag={setSelectedTag}
        // Presentational only (see ProjectsRail.tsx's file header) — Task 4
        // does not call GET /inbox/{note_id}/suggest-projects or invent
        // which note_id this screen's "one Inbox suggestion" (spec §1) is
        // even for. That data source needs its own decision, not a guess
        // made here; left null rather than fabricated. See this task's report.
        suggestion={null}
        onNewProject={() => { /* Task 5/8: create-project flow — no modal exists on the board either. */ }}
      />
      <ProjectsPane
        mode={mode}
        projects={projects}
        selectedId={selectedId}
        selectedTag={selectedTag}
        onOpenNote={onOpenNote}
        onRenamed={(oldName, newName) => {
          // FR-05: no direct setSelectedId here — see refresh()'s comment.
          // The rename lands together with the refreshed `projects` array.
          refresh({ rename: { oldName, newName } });
        }}
        onDeleted={(name) => {
          setSelectedId((prev) => (prev === name ? LOOSE_PROJECT_ID : prev));
          refresh();
        }}
        onDescriptionSaved={(name, description) => {
          // The description save itself doesn't change any COUNT (getStats
          // is untouched by it), only the registry's `description` field —
          // patch that field in place rather than a full listProjects()
          // round trip on every debounced keystroke-save.
          setProjects((prev) => prev.map((p) => (p.name === name ? { ...p, description } : p)));
        }}
      />
    </div>
  );
}

const containerStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", overflow: "hidden" };
