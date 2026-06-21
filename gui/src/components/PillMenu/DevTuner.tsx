/**
 * DevTuner.tsx
 * ------------
 * Hidden dev-only troubleshooting overlay (for_sonnet.md "Dev-only
 * troubleshooting tuner") — toggled by Ctrl+Shift+Alt+G, never shown in the
 * normal Settings UI. Sliders feed `unifiedFan` live via devTuning.ts's
 * shared store; values persist to their own localStorage key so they keep
 * applying after the overlay is closed or the app restarts. Every value
 * here only changes the fan's *shape* (radius/spacing/chip size/padding) —
 * the G1/G2 on-screen guarantees live inside `unifiedFan`/the App.tsx pill
 * clamp and hold for any slider combination.
 */
import {
  useDevTunerVisible,
  useRadialTuning,
  setRadialTuning,
  resetRadialTuning,
  RADIAL_TUNING_DEFAULTS,
} from "../../lib/devTuning";

function Slider({
  label, value, min, max, step = 1, onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#9aa1ad", marginBottom: 2 }}>
        <span>{label}</span>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{value}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ width: "100%", accentColor: "#6aa3ff" }}
      />
    </div>
  );
}

export default function DevTuner() {
  const visible = useDevTunerVisible();
  const tuning = useRadialTuning();

  if (!visible) return null;

  return (
    <div
      style={{
        position: "fixed",
        top: 12,
        right: 12,
        width: 220,
        background: "#1a1c20",
        border: "1px solid #2c2f36",
        borderRadius: 8,
        padding: 12,
        color: "#e7e9ee",
        fontSize: 12,
        zIndex: 9999,
        boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ fontSize: 12 }}>Radial fan tuner</strong>
        <button
          onClick={resetRadialTuning}
          style={{
            background: "none", border: "1px solid #2c2f36", color: "#9aa1ad",
            borderRadius: 4, fontSize: 10, padding: "2px 6px", cursor: "pointer",
          }}
        >
          Reset
        </button>
      </div>

      <Slider label="Radius (px)" value={tuning.radius} min={48} max={160} onChange={(v) => setRadialTuning({ radius: v })} />
      <Slider label="Min spacing (°)" value={tuning.minSpacingDeg} min={10} max={60} onChange={(v) => setRadialTuning({ minSpacingDeg: v })} />
      <Slider
        label="Chip max (px)"
        value={tuning.chipMax}
        min={24}
        max={48}
        onChange={(v) => setRadialTuning({ chipMax: v, chipMin: Math.min(tuning.chipMin, v) })}
      />
      <Slider
        label="Chip min (px)"
        value={tuning.chipMin}
        min={20}
        max={48}
        onChange={(v) => setRadialTuning({ chipMin: Math.min(v, tuning.chipMax) })}
      />
      <Slider label="Edge padding (px)" value={tuning.pad} min={0} max={40} onChange={(v) => setRadialTuning({ pad: v })} />
      <Slider label="Spread max arc (°)" value={tuning.spreadMaxArc} min={120} max={360} onChange={(v) => setRadialTuning({ spreadMaxArc: v })} />

      <div style={{ marginTop: 8 }}>
        <div style={{ fontSize: 11, color: "#9aa1ad", marginBottom: 4 }}>Fan style A/B override</div>
        <div style={{ display: "flex", gap: 4 }}>
          {([
            { v: null, label: "Settings" },
            { v: "spread" as const, label: "Spread" },
            { v: "capped" as const, label: "Capped" },
          ]).map(({ v, label }) => {
            const active = tuning.fanStyleOverride === v;
            return (
              <button
                key={label}
                onClick={() => setRadialTuning({ fanStyleOverride: v })}
                style={{
                  flex: 1,
                  background: active ? "#6aa3ff" : "#0e0f12",
                  color: active ? "#0e0f12" : "#e7e9ee",
                  border: "1px solid #2c2f36",
                  borderRadius: 4,
                  fontSize: 10,
                  padding: "4px 0",
                  cursor: "pointer",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ marginTop: 8, fontSize: 10, color: "#7d828c" }}>
        Defaults: radius {RADIAL_TUNING_DEFAULTS.radius}, spacing {RADIAL_TUNING_DEFAULTS.minSpacingDeg}°,
        chip {RADIAL_TUNING_DEFAULTS.chipMin}–{RADIAL_TUNING_DEFAULTS.chipMax}px, pad {RADIAL_TUNING_DEFAULTS.pad}px,
        spread {RADIAL_TUNING_DEFAULTS.spreadMaxArc}°. Ctrl+Shift+Alt+G to hide.
      </div>
    </div>
  );
}
