# Theme reference

9 themes total: 2 grayscale + 7 pastel. All tokens live in `src/index.css`
as `[data-theme="..."]` blocks; spacing/radius are shared at `:root` and
never redefined per theme. Pick a theme via the swatch picker in Settings
(`SettingsPanel.tsx`).

Grayscale themes lock to a single `--accent` (#737373, no colored CTAs).
Pastel themes intentionally relax that lock — each gets its own accent.
Semantic `--green` / `--yellow` / `--red` are state-only in every theme,
never a theme accent.

| Theme        | id           | Mode  | bg        | surface   | border    | accent    | on-accent | Notes |
|--------------|--------------|-------|-----------|-----------|-----------|-----------|-----------|-------|
| Void         | `dark`       | dark  | `#0a0a0a` | `#262626` | `#383838` | `#737373` | `#fafafa` | default, grayscale |
| Paper        | `light`      | light | `#ffffff` | `#f5f5f5` | `#e5e5e5` | `#737373` | `#fafafa` | grayscale |
| Sage         | `sage`       | light | `#f6f8f3` | `#e9efe1` | `#cddabd` | `#7fa05f` | `#f8fbf3` | green pastel |
| Sky          | `sky`        | light | `#eef6fb` | `#d7ebf5` | `#a8cfe3` | `#1f7fb3` | `#f3fafd` | saturated blue |
| Bubba Pink   | `bubba-pink` | light | `#fdf6f8` | `#f6e6ec` | `#e2bdca` | `#a2556f` | `#fdf6f8` | custom brand color, exact hex |
| Mist         | `mist`       | dark  | `#181c1d` | `#232a2b` | `#3a4546` | `#6cb8b1` | `#0d1717` | teal pastel |
| Lilac        | `lilac`      | dark  | `#1c1620` | `#2a1f30` | `#44324c` | `#c08fdd` | `#170f1b` | purple pastel |
| Sand         | `sand`       | dark  | `#1e1a16` | `#2c2620` | `#463b30` | `#cf9e5c` | `#19140f` | gold pastel |
| Wine         | `wine`       | dark  | `#160a0e` | `#241319` | `#43232d` | `#a8415f` | `#fdf2f5` | custom brand color #751E3B, brightened to `#a8415f` so it stays legible as direct text (e.g. the URL-domain label); original hex used as the conceptual "deep wine" the lighter tone is derived from |

Every theme also defines `--surface-2`, `--border-2`, `--text-1/2/3`,
`--accent-d`, `--accent-glow`, `--glass-bg/border/shadow`, `--palette-bg`,
and `--scrim` — see `src/index.css` for the full token set per theme.
