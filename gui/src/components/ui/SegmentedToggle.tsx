interface Option<K extends string> {
  key: K;
  label: string;
}

interface Props<K extends string> {
  options: Option<K>[];
  value: K;
  onChange: (key: K) => void;
  ariaLabel: string;
}

export default function SegmentedToggle<K extends string>({ options, value, onChange, ariaLabel }: Props<K>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      style={{ display: "flex", gap: 2, background: "var(--surface)", borderRadius: "var(--radius)", padding: 2 }}
    >
      {options.map((o) => (
        <button
          key={o.key}
          role="tab"
          aria-selected={value === o.key}
          onClick={() => onChange(o.key)}
          style={{
            fontSize: 11,
            padding: "4px 10px",
            borderRadius: "var(--radius-sm)",
            border: "none",
            background: value === o.key ? "var(--accent)" : "transparent",
            color: value === o.key ? "var(--on-accent)" : "var(--text-2)",
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
