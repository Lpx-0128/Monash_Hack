import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initialize } from "./api";
import "./styles.css";
const root = createRoot(document.getElementById("root")!);
root.render(
  <div className="startup" role="status">
    Connecting to Harbor Review…
  </div>,
);
initialize()
  .then((config) =>
    root.render(
      <React.StrictMode>
        <App
          initialFault={config?.fault ?? "none"}
          initialDecisionFault={config?.decision_fault ?? "none"}
        />
      </React.StrictMode>,
    ),
  )
  .catch(() =>
    root.render(
      <main className="startup">
        <h1>Unable to connect</h1>
        <p>
          The API could not initialize. Check that the Node server is running.
        </p>
        <button onClick={() => location.reload()}>Retry connection</button>
      </main>,
    ),
  );
