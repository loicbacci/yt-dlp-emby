import { Light, Narrow } from "./Shell";
import { DownloadsIdle } from "./DownloadsIdle";
import { DownloadsPlaying } from "./DownloadsPlaying";

/** Directional only. Real components in src/pages and src/components are the source of truth. */
export default {
  Idle: <DownloadsIdle />,
  "Idle · Empty": <DownloadsIdle empty />,
  "Idle · Load error": <DownloadsIdle loadError="Could not reach the server (mock)." />,
  "Idle · 360px": (
    <Narrow>
      <DownloadsIdle />
    </Narrow>
  ),
  "Idle · Light": (
    <Light>
      <DownloadsIdle />
    </Light>
  ),
  Playing: <DownloadsPlaying />,
  "Playing · Combined": <DownloadsPlaying media="combined" />,
  "Playing · 360px": (
    <Narrow>
      <DownloadsPlaying />
    </Narrow>
  ),
};
