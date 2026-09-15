import type { DropoutAction, Run, Source } from "../api";

export function RunControls({
  source,
  action,
  dryRun,
  verbose,
  force,
  exists,
  run,
  onSourceChange,
  onActionChange,
  onDryRunChange,
  onVerboseChange,
  onForceChange,
  onStart,
  onStop,
}: {
  source: Source;
  action: DropoutAction;
  dryRun: boolean;
  verbose: boolean;
  force: boolean;
  exists: boolean;
  run: Run;
  onSourceChange: (source: Source) => void;
  onActionChange: (action: DropoutAction) => void;
  onDryRunChange: (value: boolean) => void;
  onVerboseChange: (value: boolean) => void;
  onForceChange: (value: boolean) => void;
  onStart: () => void;
  onStop: () => void;
}) {
  const frozen = run.status === "running" || run.status === "stopping";
  const canStart = exists && !frozen;
  const canStop = run.status === "running";
  const downloadOptions = source === "youtube" || action === "download";

  return (
    <section class="card">
      <div class="controls-row">
        <label class="source-field">
          Source
          <select
            class="source-select"
            disabled={frozen}
            value={source}
            onChange={(e) =>
              onSourceChange((e.currentTarget as HTMLSelectElement).value as Source)
            }
          >
            <option value="youtube">YouTube</option>
            <option value="dropout">Dropout</option>
          </select>
        </label>
        {source === "dropout" && (
          <label class="source-field">
            Action
            <select
              class="source-select"
              disabled={frozen}
              value={action}
              onChange={(e) =>
                onActionChange(
                  (e.currentTarget as HTMLSelectElement).value as DropoutAction,
                )
              }
            >
              <option value="download">Download</option>
              <option value="layout">Preview remaps by folder</option>
              <option value="check">Check unmapped episodes vs Sonarr</option>
            </select>
          </label>
        )}
      </div>
      <div class="controls-row">
        {downloadOptions && (
          <label class="check-row">
            <input
              type="checkbox"
              disabled={frozen}
              checked={dryRun}
              onChange={(e) =>
                onDryRunChange((e.currentTarget as HTMLInputElement).checked)
              }
            />
            Dry run
          </label>
        )}
        <label class="check-row">
          <input
            type="checkbox"
            disabled={frozen}
            checked={verbose}
            onChange={(e) =>
              onVerboseChange((e.currentTarget as HTMLInputElement).checked)
            }
          />
          Verbose
        </label>
        {source === "dropout" && downloadOptions && (
          <label class="check-row">
            <input
              type="checkbox"
              disabled={frozen}
              checked={force}
              onChange={(e) =>
                onForceChange((e.currentTarget as HTMLInputElement).checked)
              }
            />
            Redownload existing
          </label>
        )}
      </div>
      <div class="button-row" style={{ marginTop: "12px" }}>
        <button
          type="button"
          class="btn-primary"
          disabled={!canStart}
          onClick={onStart}
        >
          Start
        </button>
        <button
          type="button"
          class="btn-danger"
          disabled={!canStop}
          onClick={onStop}
        >
          Stop
        </button>
      </div>
    </section>
  );
}
