import { useEffect } from "react";
import {
  ActivityBar,
  CommandPalette,
  ConsolePanel,
  StatusBar,
  TitleBar,
  useGlobalHotkeys,
} from "./components/Shell";
import { Notice, Spinner, ToastHost } from "./components/ui";
import { useStore } from "./lib/store";
import { Studio } from "./workspaces/Studio";
import { PatientBuilder } from "./workspaces/PatientBuilder";
import { Compounds } from "./workspaces/Compounds";
import { SystemsExplorer } from "./workspaces/SystemsExplorer";
import { Analytics } from "./workspaces/Analytics";
import { ExperimentManager } from "./workspaces/ExperimentManager";
import { EvidenceLibrary } from "./workspaces/EvidenceLibrary";
import { Reports } from "./workspaces/Reports";

export default function App() {
  const bootstrap = useStore((s) => s.bootstrap);
  const loaded = useStore((s) => s.catalogueLoaded);
  const error = useStore((s) => s.catalogueError);
  const workspace = useStore((s) => s.workspace);
  const consoleOpen = useStore((s) => s.consoleOpen);

  useGlobalHotkeys();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  return (
    <ToastHost>
      <div className="flex h-full flex-col overflow-hidden bg-base">
        <TitleBar />
        <div className="flex min-h-0 flex-1">
          <ActivityBar />
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {!loaded ? (
                <div className="flex h-full items-center justify-center">
                  <Spinner label="Loading model catalogue, drug library and reference database…" />
                </div>
              ) : error ? (
                <div className="mx-auto mt-10 max-w-2xl space-y-3 p-4">
                  <Notice tone="danger" title="The SYNTHBODY engine is not reachable">
                    {error}
                  </Notice>
                  <Notice tone="neutral" title="Start the backend">
                    <pre className="mt-1 overflow-x-auto rounded bg-void p-2 font-mono text-2xs leading-relaxed text-ink-dim">
                      {`cd backend
python -m pip install -r requirements.txt
python -m uvicorn synthbody.api.main:app --port 8000 --reload`}
                    </pre>
                    <p className="mt-2">
                      The interface is deliberately useless without the engine. Every curve shown in
                      SYNTHBODY is produced by the Python solver — there is no client-side fallback
                      and no cached demo data, so nothing is displayed that the engine did not
                      compute.
                    </p>
                  </Notice>
                  <button
                    onClick={() => void bootstrap()}
                    className="rounded-sm border border-line-strong bg-raised px-2.5 py-1 text-xs text-ink hover:bg-hover"
                  >
                    Retry connection
                  </button>
                </div>
              ) : (
                <>
                  {workspace === "studio" && <Studio />}
                  {workspace === "patient" && <PatientBuilder />}
                  {workspace === "drug" && <Compounds />}
                  {workspace === "systems" && <SystemsExplorer />}
                  {workspace === "analytics" && <Analytics />}
                  {workspace === "experiments" && <ExperimentManager />}
                  {workspace === "evidence" && <EvidenceLibrary />}
                  {workspace === "reports" && <Reports />}
                </>
              )}
            </div>
            {consoleOpen && (
              <div className="h-56 shrink-0">
                <ConsolePanel />
              </div>
            )}
          </main>
        </div>
        <StatusBar />
        <CommandPalette />
      </div>
    </ToastHost>
  );
}
