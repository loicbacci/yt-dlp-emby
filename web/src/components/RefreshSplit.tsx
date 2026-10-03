export function RefreshSplit({
  disabled,
  busy,
  title,
  onRefresh,
  onSonarrCheck,
}: {
  disabled?: boolean;
  busy?: boolean;
  title?: string;
  onRefresh: () => void;
  onSonarrCheck?: () => void;
}) {
  return (
    <div class="refresh-actions">
      <button
        type="button"
        class="btn-secondary"
        disabled={disabled}
        aria-busy={busy}
        title={title}
        onClick={onRefresh}
      >
        {busy ? <span class="spinner" aria-hidden="true" /> : null} Refresh
      </button>
      {onSonarrCheck && (
        <button
          type="button"
          class="btn-secondary"
          disabled={disabled}
          title="Check against Sonarr"
          onClick={onSonarrCheck}
        >
          Sonarr Check
        </button>
      )}
    </div>
  );
}
