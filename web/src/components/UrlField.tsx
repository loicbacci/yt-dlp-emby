export function UrlField({
  value,
  placeholder,
  disabled,
  testId,
  onChange,
}: {
  value: string;
  placeholder?: string;
  disabled?: boolean;
  testId?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label class="url-field">
      <span class="url-field-badge">URL</span>
      <input
        type="text"
        inputMode="url"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellcheck={false}
        placeholder={placeholder ?? "https://…"}
        value={value}
        disabled={disabled}
        data-testid={testId}
        onInput={(e) =>
          onChange((e.currentTarget as HTMLInputElement).value)
        }
      />
    </label>
  );
}
