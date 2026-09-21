export function UrlField({
  value,
  placeholder,
  disabled,
  testId,
  label,
  onChange,
}: {
  value: string;
  placeholder?: string;
  disabled?: boolean;
  testId?: string;
  label?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label class="url-field">
      <span class="url-field-badge">{label ?? "URL"}</span>
      <input
        type="url"
        inputMode="url"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellcheck={false}
        placeholder={placeholder ?? "https://…"}
        value={value}
        disabled={disabled}
        data-testid={testId}
        aria-label={label ?? "URL"}
        onInput={(e) => onChange((e.currentTarget as HTMLInputElement).value)}
      />
    </label>
  );
}
