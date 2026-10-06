import type { AppConfig, CookieStatus, ManifestPaths, Source } from "../api";
import { slotText } from "../api";

export type PlatformPaths = Partial<Record<Source, ManifestPaths | null>>;

export function pathsUnset(
  config: AppConfig | null | undefined,
  platformPaths?: PlatformPaths,
  platforms: Source[] = [],
): boolean {
  const library = slotText(config?.fields.library?.effective).trim();
  const oldDir = slotText(config?.fields.old_dir?.effective).trim();
  if (library && oldDir) return false;
  if (!platforms.length) return true;
  return platforms.some((platform) => {
    const paths = platformPaths?.[platform];
    return !paths?.library.effective?.trim() || !paths.old_dir.effective?.trim();
  });
}

export function cookiesMissing(cookies: CookieStatus | null | undefined): boolean {
  if (!cookies) return false;
  if (cookies.env_set) return false;
  return !cookies.jars.youtube.usable && !cookies.jars.dropout.usable;
}

export function OnboardingChecklist({
  config,
  cookies,
  seriesCount,
  planReady,
  platformPaths,
  platforms = [],
  platformPathsLoading = false,
}: {
  config: AppConfig | null | undefined;
  cookies: CookieStatus | null | undefined;
  seriesCount: number | null | undefined;
  planReady: boolean;
  platformPaths?: PlatformPaths;
  platforms?: Source[];
  platformPathsLoading?: boolean;
}) {
  // Still loading setup state — don't flash the banner.
  if (config === undefined || cookies === undefined || seriesCount == null || platformPathsLoading)
    return null;
  const stepPaths = !pathsUnset(config, platformPaths, platforms);
  const stepCookies = !cookiesMissing(cookies);
  const stepShow = (seriesCount ?? 0) > 0;
  const stepRefresh = planReady;
  if (stepPaths && stepCookies && stepShow && stepRefresh) return null;

  const steps = [
    {
      done: stepPaths,
      label: "Set library paths",
      href: "/settings",
      hint: "Settings → Config",
    },
    {
      done: stepCookies,
      label: "Add cookies",
      href: "/settings?tab=youtube",
      hint: "Settings → YouTube / Dropout",
    },
    {
      done: stepShow,
      label: "Add a show",
      href: "/series",
      hint: "Shows → Add show",
    },
    {
      done: stepRefresh,
      label: "Refresh the queue",
      href: "/",
      hint: "Downloads → Refresh queue",
    },
  ];

  return (
    <section
      class="banner banner-warn onboarding-checklist"
      role="status"
      aria-label="Setup checklist"
      data-testid="onboarding-checklist"
    >
      <strong>Finish setup ({steps.filter((s) => s.done).length}/4)</strong>
      <ol class="banner-list onboarding-steps">
        {steps.map((step) => (
          <li key={step.label} class={step.done ? "is-done" : undefined}>
            <span aria-hidden="true">{step.done ? "✓ " : "○ "}</span>
            {step.done ? (
              <span>{step.label}</span>
            ) : (
              <a href={step.href}>
                {step.label} <span class="settings-hint">({step.hint})</span>
              </a>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
