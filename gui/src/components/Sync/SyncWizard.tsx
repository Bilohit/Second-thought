/**
 * Sync/SyncWizard.tsx
 * -------------------
 * Direction A — "the connection ladder". The guided setup shown when the syncing
 * system is on but not set up yet.
 *
 * Thesis (from the approved mock): connecting two devices is a sequence, not a
 * dashboard. Drive is rung 1 because nothing syncs without it; the same-WiFi
 * accelerator is rung 2 and is explicitly optional, so skipping it forever never
 * reads as an unfinished step.
 *
 * Every step explains WHAT the feature does and WHAT it costs before asking —
 * "user choice and informed consent are critical" (E6 spec, the user's words).
 *
 * Stateful orchestration only: which view/step is showing is resolved by the pure
 * resolveSyncSetup() in lib/syncSetup.ts. This file renders and reports intent.
 */
import type { ReactNode } from "react";
import type { WizardStep, StatusTone } from "../../lib/syncSetup";
import type { DriveAuthStatus } from "../../lib/api";
import { CheckIcon, AlertIcon } from "../PillMenu/icons";
import { BTN_SECONDARY } from "../ui/styles";
import { Note, StatusDot, TONE_COLOR } from "./parts";

interface Props {
  compact: boolean;
  step: WizardStep;
  drive: DriveAuthStatus | null;
  driveTone: StatusTone;
  /** True while the connectDrive() promise is in flight (a real browser consent window). */
  connecting: boolean;
  driveError: string | null;
  onConnectDrive: () => void;
  /** Stop waiting on the consent window. Cannot close the browser tab — see the copy. */
  onStopWaiting: () => void;
  onSkipDrive: () => void;
  /** Step 2 body — the absorbed PairingPanel, rendered by the parent. */
  lanSection: ReactNode;
  onLanDone: () => void;
  onSkipLan: () => void;
  onCancel: () => void;
}

type NodeState = "pending" | "active" | "done" | "error";

// ── The rail node: hollow when pending. Never green for an unknown state. ────

function LadderNode({ state }: { state: NodeState }) {
  const NODE = 16;
  const box: React.CSSProperties = {
    position: "absolute", left: 0, top: 9, width: NODE, height: NODE,
    display: "flex", alignItems: "center", justifyContent: "center",
  };
  if (state === "done") {
    return (
      <span style={{ ...box, color: "var(--green)", animation: "checkPop 220ms var(--hover-ease-out) both" }} aria-hidden="true">
        <CheckIcon size={14} />
      </span>
    );
  }
  if (state === "error") {
    return (
      <span style={{ ...box, color: "var(--red)" }} aria-hidden="true">
        <AlertIcon size={14} />
      </span>
    );
  }
  if (state === "active") {
    // Spinner ring — the sanctioned round instrument affordance.
    return (
      <span style={{ ...box, color: "var(--yellow)" }} aria-hidden="true">
        <svg width={14} height={14} viewBox="0 0 16 16" style={{ animation: "spin 900ms linear infinite" }}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeDasharray="26" strokeDashoffset="18" />
        </svg>
      </span>
    );
  }
  return (
    <span style={box} aria-hidden="true">
      <span style={{ width: 7, height: 7, borderRadius: "50%", border: "1.5px solid var(--border)", background: "transparent" }} />
    </span>
  );
}

const RAIL_COLOR: Record<NodeState, string> = {
  done: "var(--green)",
  error: "var(--red)",
  active: "var(--yellow)",
  pending: "var(--border)",
};

function Rung({
  node, title, summary, summaryTone, open, locked, children, index,
}: {
  node: NodeState;
  title: string;
  summary: string;
  summaryTone: StatusTone;
  open: boolean;
  locked: boolean;
  children: ReactNode;
  index: number;
}) {
  return (
    <li
      className="sync-rise"
      style={{
        position: "relative",
        paddingLeft: 26,
        paddingBottom: 8,
        listStyle: "none",
        opacity: locked ? 0.4 : 1,
        animationDelay: `${index * 45}ms`, // locked 45ms stagger
        transition: "opacity 260ms var(--hover-ease-out)",
      }}
    >
      {/* Dashed connector, coloured by this rung's own state: the rail fills as the ladder advances. */}
      <span
        aria-hidden="true"
        style={{
          position: "absolute", left: 8, top: 26, bottom: 0, width: 0,
          borderLeft: `1px dashed ${RAIL_COLOR[node]}`,
          transform: "translateX(-0.5px)",
          transition: "border-color 260ms var(--hover-ease-out)",
        }}
      />
      <LadderNode state={node} />

      <div style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "9px 8px 9px 0", borderBottom: "1px solid var(--border-2)",
      }}>
        <span style={{ fontSize: 12.5, color: "var(--text-1)", letterSpacing: "-0.01em", flexShrink: 0 }}>
          {title}
        </span>
        <span
          style={{
            fontSize: 11, flex: 1, minWidth: 0,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            color: summaryTone === "none" ? "var(--text-2)" : TONE_COLOR[summaryTone],
          }}
        >
          {summary}
        </span>
        {/* No disclosure chevron: this is a stepper, not an accordion. The open rung
            is whichever step you are on, so a chevron would advertise a control that
            does not exist. */}
      </div>

      <div className="sync-disclose" data-open={open}>
        <div>
          <div style={{ padding: "12px 0 16px" }}>{children}</div>
        </div>
      </div>
    </li>
  );
}

// ── Steps ───────────────────────────────────────────────────────────────────

// The Connect action itself lives in the wizard's footer with the other step
// actions, so this body only ever explains — it never carries a second Connect button.
function DriveStep({
  drive, connecting, driveError, onStopWaiting, compact,
}: Pick<Props, "drive" | "connecting" | "driveError" | "onStopWaiting" | "compact">) {
  // The one state the Connect button cannot fix — say so instead of offering it.
  if (drive && !drive.client_secret_present) {
    return (
      <div>
        <Note tone="fail" style={{ marginBottom: 8 }}>Google credentials file not found.</Note>
        <Note style={{ marginBottom: 12 }}>
          Drive cannot be connected until an OAuth client file is in place. This is the one state the
          Connect button cannot fix, so it is not offered here.
        </Note>
      </div>
    );
  }

  if (connecting || drive?.connecting) {
    return (
      <div>
        <div style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 11, color: "var(--text-2)", marginBottom: 8 }}>
          <StatusDot tone="wait" />
          Waiting for the browser consent window.
        </div>
        <Note style={{ marginBottom: 12 }}>
          Finish signing in on the browser tab that just opened. Nothing is saved until you do. If you
          closed it by accident, stop waiting and try again.
        </Note>
        <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={onStopWaiting}>
          Stop waiting
        </button>
        <Note style={{ marginTop: 8 }}>
          This only stops this panel waiting. It cannot close the browser window — if you finish signing
          in there, Drive still connects.
        </Note>
      </div>
    );
  }

  return (
    <div>
      {/* What it does, then what it costs — before asking. */}
      <Note style={{ marginBottom: 12 }}>
        Drive is the sync. Your notes move both ways through a folder in your Google Drive, in batches.
        Nothing on this tab does anything until it is connected.
        {!compact && " Your notes stay on this computer too — Drive is the shared copy, not the only one."}
      </Note>
      {driveError && <Note tone="fail" style={{ marginBottom: 10 }}>{driveError}</Note>}
      <Note style={{ marginBottom: 12 }}>
        Costs: a Google sign-in, and your notes stored in your own Drive account.
        {!compact && " Takes about 30 seconds."}
      </Note>
    </div>
  );
}

function LanStep({ lanSection, compact }: { lanSection: ReactNode; compact: boolean }) {
  return (
    <div>
      <Note style={{ marginBottom: 12 }}>
        Optional. When your phone is on the same WiFi as this computer, files can move directly between
        them instead of waiting for the next Drive batch.
        {!compact && " It is only a shortcut: Drive still decides what is correct, and everything works exactly the same without it."}
      </Note>
      <Note style={{ marginBottom: 12 }}>
        Costs: this computer listens on your local network while it is on. Skipping changes nothing
        about what syncs, only how fast.
      </Note>
      {lanSection}
    </div>
  );
}

// ── The wizard ──────────────────────────────────────────────────────────────

export default function SyncWizard({
  compact, step, drive, driveTone, connecting, driveError,
  onConnectDrive, onStopWaiting, onSkipDrive,
  lanSection, onLanDone, onSkipLan, onCancel,
}: Props) {
  const onDrive = step === "drive";
  const driveConnected = drive?.connected ?? false;
  const secretMissing = drive ? !drive.client_secret_present : false;

  const driveNode: NodeState =
    driveConnected ? "done" : (connecting || drive?.connecting) ? "active" : secretMissing ? "error" : "pending";
  const lanNode: NodeState = onDrive ? "pending" : "active";

  const driveSummary =
    driveConnected ? "connected"
    : secretMissing ? "credentials file missing"
    : (connecting || drive?.connecting) ? "waiting for browser consent"
    : "not connected · nothing syncs yet";

  const setupDone = driveConnected;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        <Rung
          index={0}
          node={driveNode}
          title="Google Drive"
          summary={driveSummary}
          summaryTone={driveTone}
          open={onDrive}
          locked={false}
        >
          <DriveStep
            drive={drive}
            connecting={connecting}
            driveError={driveError}
            onStopWaiting={onStopWaiting}
            compact={compact}
          />
        </Rung>

        <Rung
          index={1}
          node={lanNode}
          title="Same-WiFi shortcut"
          summary={onDrive ? "waiting for Drive" : "optional"}
          summaryTone="none"
          open={!onDrive}
          locked={onDrive}
        >
          <LanStep lanSection={lanSection} compact={compact} />
        </Rung>

        {/* Terminus: the ladder's end-cap, not a third step. */}
        <li style={{ position: "relative", paddingLeft: 26, listStyle: "none", display: "flex", minHeight: 20 }}>
          <span aria-hidden="true" style={{ position: "absolute", left: 0, top: 0, width: 16, height: 9 }}>
            <span style={{
              position: "absolute", left: 8, top: 0, height: 9, width: 0,
              borderLeft: `1px dashed ${setupDone ? "var(--green)" : "var(--border)"}`,
              transform: "translateX(-0.5px)", transition: "border-color 260ms var(--hover-ease-out)",
            }} />
            <span style={{
              position: "absolute", left: 2, top: 8, width: 12, height: 0,
              borderTop: `1px solid ${setupDone ? "var(--green)" : "var(--border)"}`,
              transition: "border-color 260ms var(--hover-ease-out)",
            }} />
          </span>
          <span style={{ fontSize: 11, color: setupDone ? "var(--text-2)" : "var(--text-3)" }}>
            {setupDone ? "Sync is set up. The step below is optional." : "Two steps. That is the whole setup."}
          </span>
        </li>
      </ol>

      {/* Actions. One escape control per step, labelled for what it actually does there. */}
      <div style={{
        display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
        marginTop: 20, paddingTop: 12, borderTop: "1px solid var(--border-2)",
      }}>
        {onDrive ? (
          <>
            {/* At step 1 the global escape IS the skip: there is nothing after Drive to
                advance to, so a separate Cancel would be the same button twice. */}
            <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={onSkipDrive}>
              Skip for now
            </button>
            {!secretMissing && !connecting && !drive?.connecting && (
              <button
                type="button"
                className="btn-hover"
                style={{
                  ...BTN_SECONDARY,
                  background: "var(--text-1)", color: "var(--bg)",
                  borderColor: "var(--text-1)", fontWeight: 600,
                  marginLeft: "auto",
                }}
                onClick={onConnectDrive}
              >
                Connect Google Drive
              </button>
            )}
          </>
        ) : (
          <>
            <button type="button" className="btn-hover" style={BTN_SECONDARY} onClick={onCancel}>
              Cancel
            </button>
            <button type="button" className="btn-hover" style={{ ...BTN_SECONDARY, marginLeft: "auto" }} onClick={onSkipLan}>
              Skip
            </button>
            <button
              type="button"
              className="btn-hover"
              style={{
                ...BTN_SECONDARY,
                background: "var(--text-1)", color: "var(--bg)",
                borderColor: "var(--text-1)", fontWeight: 600,
              }}
              onClick={onLanDone}
            >
              Done
            </button>
          </>
        )}
      </div>

      {!onDrive && (
        <Note style={{ marginTop: 10 }}>
          Cancel undoes the same-WiFi change and returns to the sync panel. It cannot undo the Google
          sign-in — that grant is real and stays until you disconnect Drive.
        </Note>
      )}
    </div>
  );
}
