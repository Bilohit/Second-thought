/**
 * searchResultState.ts
 * ---------------------
 * FR-13: which empty/qualified state the Search panel's result list is in,
 * for a settled (non-loading, non-error) result set on a non-blank query.
 *
 * GET /search returns at most one `rescued: true` row, and only when the
 * keyword tier found nothing AND every semantic candidate fell below the
 * similarity floor (vault_admin.py's search_captures, `keyword_hit =
 * bool(results)`; vector_store.semantic_search's `include_below_threshold`).
 * A rescued row and a normal result set are mutually exclusive by
 * construction, so this never has to arbitrate between them -- it only
 * has to name which of the three states a settled response landed in:
 *
 *   - "empty"   genuinely nothing in the vault relates to the query
 *   - "rescued" one weak/related match exists, below the confidence floor
 *   - "results" one or more ordinary (keyword or passing-semantic) hits
 */
import type { SearchResult } from "./api";

export type SearchResultState =
  | { kind: "empty" }
  | { kind: "rescued"; result: SearchResult }
  | { kind: "results"; results: SearchResult[] };

export function classifySearchResults(results: SearchResult[]): SearchResultState {
  if (results.length === 0) return { kind: "empty" };
  const rescued = results.find((r) => r.rescued === true);
  if (rescued) return { kind: "rescued", result: rescued };
  return { kind: "results", results };
}
