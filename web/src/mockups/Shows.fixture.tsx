import { MOCK_SHOWS } from "./mockCatalog";
import { ShowDetail } from "./ShowDetail";
import { ShowsList } from "./ShowsList";

export default {
  List: <ShowsList />,
  "List · Reading manifests": <ShowsList loading="manifests" />,
  "List · Refreshing": <ShowsList loading="refresh" />,
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
