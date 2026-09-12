import type { Run, Source } from "../api";

export function RunControls({
  source,
  dryRun,
  verbose,
  force,
  exists,
  run,
  onSourceChange,
  onDryRunChange,
  onVerboseChange,
  onForceChange,
  onStart,
  onStop,
}: {
  source: Source;
  dryRun: boolean;
  verbose: boolean;
  force: boolean;
  exists: boolean;
  run: Run;
  onSourceChange: (source: Source) => void;
  onDryRunChange: (value: boolean) => void;
  onVerboseChange: (value: boolean) => void;
  onForceChange: (value: boolean) => void;
  onStart: () => void;
  onStop: () => void;
}) {
  const frozen = run.status === "running" || run.status === "stopping";
  const canStart = exists && !frozen;
  const canStop = run.status === "running";

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
      </div>
      <div class="controls-row">
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
        {source === "dropout" && (
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
