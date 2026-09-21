import { useEffect, useState } from "preact/hooks";
import { ApiError, type SeriesDetail, type Source, apiClient } from "../../api";
import { ManifestEditor } from "../ManifestEditor";
import { Skeleton } from "../Skeleton";

export function SeriesYamlPanel({
  platform,
  slug,
  onSaved,
}: {
  platform: Source;
  slug: string;
  onSaved: (detail: SeriesDetail) => void;
}) {
  const [text, setText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [file, setFile] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    apiClient
      .getSeriesYaml(platform, slug)
      .then((body) => {
        if (cancelled) return;
        setText(body.text);
        setSavedText(body.text);
        setFile(body.file);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Could not load YAML");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [platform, slug]);

  const save = async () => {
    setError(null);
    try {
      const detail = await apiClient.putSeriesYaml(platform, slug, text);
      const nextSlug = detail.slug || slug;
      const fresh = await apiClient.getSeriesYaml(platform, nextSlug);
      setText(fresh.text);
      setSavedText(fresh.text);
      setFile(fresh.file);
      onSaved(detail);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  };

  if (loading) {
    return (
      <section class="card" role="status">
        <Skeleton width="8rem" height="1rem" />
        <Skeleton width="100%" height="16rem" />
      </section>
    );
  }

  return (
    <ManifestEditor
      source={platform}
      text={text}
      savedText={savedText}
      exists
      error={error}
      activePath={file}
      onChange={setText}
      onSave={() => void save()}
    />
  );
}
