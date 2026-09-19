import { DownloadsIdle } from "./DownloadsIdle";
import { DownloadsPlaying } from "./DownloadsPlaying";

export default {
  Idle: <DownloadsIdle />,
  Playing: <DownloadsPlaying />,
  "Playing · Combined": <DownloadsPlaying media="combined" />,
};
