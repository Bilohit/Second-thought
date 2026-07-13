/**
 * pillTypes.ts
 * ------------
 * Shared pill-shape type aliases, lifted out of PillOverlay.tsx so that
 * SettingsPanel.tsx (and any other consumer) can depend on the *shape* of
 * these values without importing PillOverlay.tsx itself. That import was
 * the choke-point edge closing the graphify-flagged
 * CompactSettings -> SettingsPanel -> PillOverlay -> CompactSettings
 * (and FullWindow-inclusive 4-file) import cycles under
 * gui/src/components/. Type-only, no runtime code — do not add value
 * exports here.
 */
export type PillMode = "capsule" | "minimal";
export type PillCorner = "sharp" | "rounded";
