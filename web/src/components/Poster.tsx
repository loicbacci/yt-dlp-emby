import { useEffect, useState } from "preact/hooks";

export function posterLetter(name: string): string {
  const match = /[a-z0-9]/i.exec(name.trim());
  return match ? match[0].toUpperCase() : "?";
}

export function posterShowsImage(
  src: string | null | undefined,
  failedSrc: string | null,
): boolean {
  return Boolean(src) && src !== failedSrc;
}

export function Poster({
  src,
  letter,
  size = "md",
  alt = "",
}: {
  src?: string | null;
  letter: string;
  size?: "sm" | "md" | "lg" | "now";
  alt?: string;
}) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setFailedSrc(null);
    setLoaded(false);
  }, [src]);

  const showImg = posterShowsImage(src, failedSrc);
  return (
    <div
      class={`poster poster-${size}${!loaded && showImg ? " is-loading" : ""}`}
      aria-hidden={!alt}
    >
      {showImg ? (
        <img
          src={src!}
          alt={alt}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => setFailedSrc(src ?? null)}
        />
      ) : (
        <span class="poster-fallback">{letter}</span>
      )}
    </div>
  );
}
