import { useState } from "preact/hooks";

export function posterLetter(name: string): string {
  const match = /[a-z0-9]/i.exec(name.trim());
  return match ? match[0].toUpperCase() : "?";
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
  const [failed, setFailed] = useState(false);
  const showImg = Boolean(src) && !failed;
  return (
    <div class={`poster poster-${size}`} aria-hidden={!alt}>
      {showImg ? (
        <img
          src={src!}
          alt={alt}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <span class="poster-fallback">{letter}</span>
      )}
    </div>
  );
}
