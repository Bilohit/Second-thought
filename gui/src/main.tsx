import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initLogger, logger } from "./lib/logger";
import { applyMotionVars } from "./lib/motionVars";
// Geist Mono — bundled locally so the offline desktop app honors the font
// lock without a network fetch. 400 (body) + 500/600 (emphasis) weights.
import "@fontsource/geist-mono/400.css";
import "@fontsource/geist-mono/500.css";
import "@fontsource/geist-mono/600.css";
import "./index.css";

initLogger();
// Morph durations → CSS custom properties, before first paint so no transition
// ever runs against a missing variable. See lib/motionVars.ts: the TS constants
// are the single source and index.css consumes them, so a redesign can no
// longer drift the hand-tuned motion by editing one side of a duplicated value.
applyMotionVars();
logger.info("app", "Mounting React root");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
