import { Light, Narrow } from "./Shell";
import { MOCK_SHOWS } from "./mockCatalog";
import { ShowDetail } from "./ShowDetail";
import { ShowsList } from "./ShowsList";

/** Directional only. Real components in src/pages and src/components are the source of truth. */
export default {
  List: <ShowsList />,
  "List · Reading manifests": <ShowsList loading="manifests" />,
  "List · Refreshing": <ShowsList loading="refresh" />,
  "List · Empty": <ShowsList empty />,
  "List · Load error": <ShowsList loadError="Could not reach the server (mock)." />,
  "List · 360px": (
    <Narrow>
      <ShowsList />
    </Narrow>
  ),
  "List · Light": (
    <Light>
      <ShowsList />
    </Light>
  ),
  ...Object.fromEntries(
    MOCK_SHOWS.map((show) => [show.name, <ShowDetail slug={show.id} />]),
  ),
  "Dimension 20 · Refreshing": (
    <ShowDetail slug="dimension-20" loading="refreshing" />
  ),
  "Dimension 20 · Mapping": <ShowDetail slug="dimension-20" tab="mapping" />,
  "Dimension 20 · Mapping refresh": (
    <ShowDetail slug="dimension-20" tab="mapping" loading="refreshing" />
  ),
  "Dimension 20 · Remap": (
    <ShowDetail slug="dimension-20" tab="mapping" remapOpen />
  ),
};
