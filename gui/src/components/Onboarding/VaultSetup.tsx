/**
 * Onboarding/VaultSetup.tsx
 * -------------------------
 * First-run vault-setup wizard (ISS-002 / P-WIZARD), built from the approved
 * mock (iss002-vault-setup-mock.html): a 3-step flow -- Location -> Folders
 * -> Ready -- that skips the Folders step entirely when the chosen path is
 * already an existing vault with user categories.
 *
 * Stateful orchestration only: which folders are selected, what step is
 * showing, and the existing-vault detection are all resolved by the pure
 * helpers in lib/vaultSetup.ts (sibling vaultSetup.test.ts). This file
 * fetches, commits (POST /vault/setup), and renders.
 *
 * Rendered by App.tsx BEFORE the pill/capture view whenever GET /config has
 * no `[vault] root` configured (isFirstRun). It never hardcodes the category
 * enum -- the 10-folder catalog only seeds folder names + starter routing
 * descriptions for the server to create on disk; models.py's category enum
 * is still built live from whatever folders exist at capture time.
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { checkVaultSetup, getVaultCategories, postVaultSetup, type VaultSetupCheckResult } from "../../lib/api";
import { MenuIcon, CheckIcon, AlertIcon } from "../PillMenu/icons";
import { BTN_PRIMARY, BTN_SECONDARY, INPUT_STYLE, focusRing, blurRing } from "../ui/styles";
import type { PillCorner } from "../PillOverlay";
import {
  FOLDER_CATALOG,
  DEFAULT_SELECTED,
  MAX_STARTER_FOLDERS,
  toggleFolderSelection,
  nextStep,
  prevStep,
  totalVisibleSteps,
  visibleStepNumber,
  canAdvance,
  buildFoldersPayload,
  type WizardStep,
} from "../../lib/vaultSetup";

interface Props {
  pillCorner: PillCorner;
  onComplete: () => void;
}

const WIN_W = 720;

export default function VaultSetup({ pillCorner, onComplete }: Props) {
  const [step, setStep] = useState<WizardStep>("location");
  const [vaultRoot, setVaultRoot] = useState("");
  const [checkResult, setCheckResult] = useState<VaultSetupCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [selected, setSelected] = useState<string[]>(DEFAULT_SELECTED);
  const [descriptions, setDescriptions] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Existing-vault-with-user-folders is the only signal that skips step 2 --
  // an existing but empty directory still needs the folder picker.
  const existingVaultFound = checkResult?.has_categories === true;

  // Prefill with the server's own resolved default (mirrors SettingsPanel's
  // handlePickFolder precedent: never guess a client-side path).
  useEffect(() => {
    let cancelled = false;
    getVaultCategories()
      .then((res) => { if (!cancelled && res.vault_root) setVaultRoot(res.vault_root); })
      .catch(() => { /* leave blank -- user can Browse or type */ });
    return () => { cancelled = true; };
  }, []);

  // Re-check whenever the candidate path changes (initial prefill + every Browse).
  const checkSeq = useRef(0);
  useEffect(() => {
    if (!vaultRoot.trim()) { setCheckResult(null); return; }
    const seq = ++checkSeq.current;
    setChecking(true);
    checkVaultSetup(vaultRoot)
      .then((res) => { if (checkSeq.current === seq) setCheckResult(res); })
      .catch(() => { if (checkSeq.current === seq) setCheckResult(null); })
      .finally(() => { if (checkSeq.current === seq) setChecking(false); });
  }, [vaultRoot]);

  const handleBrowse = useCallback(async () => {
    const picked = await openDialog({ directory: true, multiple: false });
    if (picked && typeof picked === "string") setVaultRoot(picked);
  }, []);

  const goNext = useCallback(() => {
    setError(null);
    setStep((s) => nextStep(s, existingVaultFound));
  }, [existingVaultFound]);
  const goBack = useCallback(() => {
    setError(null);
    setStep((s) => prevStep(s, existingVaultFound));
  }, [existingVaultFound]);

  const handleCreate = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    try {
      const folders = existingVaultFound ? [] : buildFoldersPayload(selected, descriptions);
      await postVaultSetup(vaultRoot, folders);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set up the vault.");
    } finally {
      setSubmitting(false);
    }
  }, [existingVaultFound, selected, descriptions, vaultRoot, onComplete]);

  const canGoNext =
    step === "location" ? vaultRoot.trim().length > 0 && !checking : canAdvance(step, selected.length);

  return (
    <div style={{ width: "100vw", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "transparent" }}>
      <div
        className="fw-shell"
        data-corner={pillCorner}
        role="dialog"
        aria-label="Set up your vault"
        style={{
          width: WIN_W, maxWidth: "100%", maxHeight: "calc(100vh - 48px)",
          display: "flex", flexDirection: "column",
          background: "var(--surface)", border: "1px solid var(--border)",
          overflow: "hidden",
        }}
      >
        <TitleBar step={step} existingVaultFound={existingVaultFound} />

        <div className="fw-chrome" data-corner={pillCorner} style={{ padding: 32, overflow: "auto", flex: 1 }}>
          {step === "location" && (
            <LocationStep
              vaultRoot={vaultRoot}
              onChangeRoot={setVaultRoot}
              onBrowse={handleBrowse}
              checking={checking}
              checkResult={checkResult}
            />
          )}
          {step === "folders" && (
            <FoldersStep
              selected={selected}
              onToggle={(name) => setSelected((s) => toggleFolderSelection(s, name))}
              onClearAll={() => setSelected([])}
              descriptions={descriptions}
              onEditDescription={(name, value) => setDescriptions((d) => ({ ...d, [name]: value }))}
            />
          )}
          {step === "ready" && (
            <ReadyStep vaultRoot={vaultRoot} selected={selected} existingVaultFound={existingVaultFound} checkResult={checkResult} />
          )}
          {error && (
            <div style={{ marginTop: 16, fontSize: 12, color: "var(--red)" }}>{error}</div>
          )}
        </div>

        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
          padding: "14px 32px", borderTop: "1px solid var(--border)", background: "var(--bg)",
        }}>
          <div style={{ color: "var(--text-3)", fontSize: 11 }}>
            Step {visibleStepNumber(step, existingVaultFound)} of {totalVisibleSteps(existingVaultFound)}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {step !== "location" && (
              <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={goBack} disabled={submitting}>
                Back
              </button>
            )}
            {step === "ready" ? (
              <button
                type="button"
                className="btn-hover"
                style={{ ...BTN_PRIMARY, opacity: submitting ? 0.6 : 1, cursor: submitting ? "not-allowed" : "pointer" }}
                onClick={handleCreate}
                disabled={submitting}
              >
                {submitting ? "Creating…" : "Create vault"}
              </button>
            ) : (
              <button
                type="button"
                className="btn-hover"
                style={{ ...BTN_PRIMARY, opacity: canGoNext ? 1 : 0.4, cursor: canGoNext ? "pointer" : "not-allowed" }}
                onClick={goNext}
                disabled={!canGoNext}
              >
                Continue
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Titlebar + stepper ───────────────────────────────────────────────────

function TitleBar({ step, existingVaultFound }: { step: WizardStep; existingVaultFound: boolean }) {
  const dots: { key: WizardStep; label: string }[] = existingVaultFound
    ? [{ key: "location", label: "Location" }, { key: "ready", label: "Ready" }]
    : [{ key: "location", label: "Location" }, { key: "folders", label: "Folders" }, { key: "ready", label: "Ready" }];
  const order: WizardStep[] = existingVaultFound ? ["location", "ready"] : ["location", "folders", "ready"];
  const stepIdx = order.indexOf(step);

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "12px 16px", borderBottom: "1px solid var(--border)", background: "var(--bg)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, letterSpacing: "0.02em", color: "var(--text-2)" }}>
        <MenuIcon target="vault" size={16} />
        <span><b style={{ color: "var(--text-1)", fontWeight: 600 }}>Second Thought</b> · first-run setup</span>
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12, fontSize: 11 }}>
        {dots.map((d, i) => {
          const idx = order.indexOf(d.key);
          const active = idx === stepIdx;
          const done = idx < stepIdx;
          return (
            <span key={d.key} style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {i > 0 && <span style={{ width: 18, height: 1, background: "var(--border)" }} />}
              <span style={{ display: "flex", alignItems: "center", gap: 6, color: active ? "var(--text-1)" : done ? "var(--text-2)" : "var(--text-3)" }}>
                <span style={{
                  width: 18, height: 18, borderRadius: "50%",
                  border: `1px solid ${active ? "var(--text-1)" : "var(--border)"}`,
                  background: active ? "var(--accent-d)" : "transparent",
                  display: "grid", placeItems: "center", fontSize: 10,
                }}>
                  {done ? <CheckIcon size={10} /> : i + 1}
                </span>
                {d.label}
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ── Step 1: Location ─────────────────────────────────────────────────────

function LocationStep({
  vaultRoot, onChangeRoot, onBrowse, checking, checkResult,
}: {
  vaultRoot: string;
  onChangeRoot: (v: string) => void;
  onBrowse: () => void;
  checking: boolean;
  checkResult: VaultSetupCheckResult | null;
}) {
  const exists = !checking && checkResult?.has_categories === true;

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em", marginBottom: 8 }}>
        Where should your vault live?
      </h1>
      <p style={{ color: "var(--text-2)", fontSize: 13, maxWidth: "60ch", marginBottom: 24 }}>
        Your vault is a plain folder of Markdown notes — the source of truth Second Thought
        files everything into. Pick where it lives; you can move it later in Settings.
      </p>

      <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
        Vault location
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={vaultRoot}
          onChange={(e) => onChangeRoot(e.target.value)}
          placeholder="~/Documents/SecondThoughtVault"
          style={{ ...INPUT_STYLE, flex: 1 }}
          onFocus={focusRing}
          onBlur={blurRing}
        />
        <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={onBrowse}>
          Browse…
        </button>
      </div>

      {checkResult && !checking && (
        <div style={{
          marginTop: 16, display: "flex", gap: 12, alignItems: "flex-start",
          padding: "12px 16px", border: "1px solid var(--border)", background: "var(--bg)",
        }}>
          <span style={{ color: exists ? "var(--green)" : "var(--yellow)", flex: "none", marginTop: 1 }}>
            {exists ? <CheckIcon size={16} /> : <AlertIcon size={16} />}
          </span>
          <div>
            <div style={{ fontSize: 13 }}>
              {exists ? "Existing vault found — we'll use it as-is." : "No existing vault here — we'll set one up."}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
              {exists
                ? "Your folders and notes are already set up. Setup will skip the folder step."
                : "Next you'll pick a few starter folders. Your scratchpad and internal index folders are created automatically."}
            </div>
          </div>
        </div>
      )}
      {checking && (
        <div style={{ marginTop: 16, fontSize: 12, color: "var(--text-3)" }}>Checking…</div>
      )}
    </div>
  );
}

// ── Step 2: Folders ───────────────────────────────────────────────────────

function FoldersStep({
  selected, onToggle, onClearAll, descriptions, onEditDescription,
}: {
  selected: string[];
  onToggle: (name: string) => void;
  onClearAll: () => void;
  descriptions: Record<string, string>;
  onEditDescription: (name: string, value: string) => void;
}) {
  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em", marginBottom: 8 }}>
        Pick your starter folders
      </h1>
      <p style={{ color: "var(--text-2)", fontSize: 13, maxWidth: "60ch", marginBottom: 24 }}>
        These become the categories Second Thought auto-files captures into. Choose up to 5 to
        start — the description under each teaches the AI what belongs there.
      </p>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ fontSize: 12, color: "var(--text-2)" }}>
          <b style={{ color: "var(--text-1)" }}>{selected.length}</b> / {MAX_STARTER_FOLDERS} selected
        </div>
        <button type="button" className="btn-hover" style={{ ...BTN_SECONDARY, padding: "6px 10px", fontSize: 12, background: "transparent" }} onClick={onClearAll}>
          Clear all
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {FOLDER_CATALOG.map((f) => {
          const isSel = selected.includes(f.name);
          const atCap = selected.length >= MAX_STARTER_FOLDERS && !isSel;
          return (
            <div
              key={f.name}
              onClick={() => !atCap && onToggle(f.name)}
              style={{
                border: `1px solid ${isSel ? "var(--text-1)" : "var(--border)"}`,
                background: isSel ? "var(--accent-d)" : "var(--bg)",
                padding: "12px 16px",
                cursor: atCap ? "not-allowed" : "pointer",
                opacity: atCap ? 0.4 : 1,
                transition: "border-color 0.2s var(--hover-ease-out), background 0.2s var(--hover-ease-out)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{
                  width: 18, height: 18, borderRadius: 4, flex: "none",
                  border: `1px solid ${isSel ? "var(--text-1)" : "var(--border)"}`,
                  background: isSel ? "var(--text-1)" : "transparent",
                  color: "var(--bg)", display: "grid", placeItems: "center",
                }}>
                  {isSel && <CheckIcon size={12} />}
                </span>
                <MenuIcon target="vault" size={15} />
                <span style={{ fontSize: 14, fontWeight: 600 }}>{f.name}</span>
              </div>
              {isSel && (
                <div style={{ marginTop: 12 }}>
                  <textarea
                    value={descriptions[f.name] ?? f.description}
                    onChange={(e) => onEditDescription(f.name, e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    rows={2}
                    style={{
                      width: "100%", resize: "vertical", minHeight: 38, fontFamily: "inherit",
                      fontSize: 12, color: "var(--text-2)", background: "var(--surface)",
                      border: "1px solid var(--border)", borderRadius: 4, padding: "8px 10px", lineHeight: 1.45,
                    }}
                    onFocus={focusRing}
                    onBlur={blurRing}
                  />
                  <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 4, letterSpacing: "0.02em" }}>
                    AI routing description — captures matching this go to {f.name}/
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div style={{
        marginTop: 24, display: "flex", gap: 12, alignItems: "flex-start", fontSize: 12,
        color: "var(--text-2)", padding: "12px 16px", border: "1px dashed var(--border)",
      }}>
        <span style={{ color: "var(--text-3)", flex: "none", marginTop: 1 }}>
          <AlertIcon size={15} />
        </span>
        <span>
          You can add, rename, remove, or re-describe folders any time in <b style={{ color: "var(--text-1)" }}>Library → Vault</b>.
          Descriptions are what drive auto-categorization — edit them whenever routing feels off.
        </span>
      </div>
    </div>
  );
}

// ── Step 3: Ready ─────────────────────────────────────────────────────────

function ReadyStep({
  vaultRoot, selected, existingVaultFound, checkResult,
}: {
  vaultRoot: string;
  selected: string[];
  existingVaultFound: boolean;
  checkResult: VaultSetupCheckResult | null;
}) {
  const chips = existingVaultFound ? (checkResult?.categories ?? []) : selected;
  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.01em", marginBottom: 8 }}>
        Ready to create your vault
      </h1>
      <p style={{ color: "var(--text-2)", fontSize: 13, maxWidth: "60ch", marginBottom: 24 }}>
        {existingVaultFound
          ? "We'll point Second Thought at this vault as-is — nothing on disk changes."
          : "We'll create the folder, your chosen categories, and the system folders. Nothing is sent anywhere — this is all local until you connect Drive."}
      </p>

      <ReviewRow k="Location" v={vaultRoot} />
      <ReviewRow
        k={existingVaultFound ? "Existing categories" : "Starter folders"}
        v={
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "flex-end" }}>
            {chips.length === 0
              ? <span style={chipStyle}>(none)</span>
              : chips.map((c) => <span key={c} style={chipStyle}>{c}</span>)}
          </div>
        }
      />
      <ReviewRow k="System folders" v="_scratchpad · .omni_capture" />
      <ReviewRow k="Auto-sync" v="On launch · interval off until you pick one" last />
    </div>
  );
}

const chipStyle: CSSProperties = {
  fontSize: 11, padding: "3px 8px", border: "1px solid var(--border)", borderRadius: 20, color: "var(--text-1)",
};

function ReviewRow({ k, v, last }: { k: string; v: ReactNode; last?: boolean }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", gap: 16, padding: "12px 0",
      borderBottom: last ? "none" : "1px solid var(--border-2)",
    }}>
      <span style={{ color: "var(--text-3)", fontSize: 12, flex: "none" }}>{k}</span>
      <span style={{ color: "var(--text-1)", fontSize: 13, textAlign: "right" }}>{v}</span>
    </div>
  );
}
