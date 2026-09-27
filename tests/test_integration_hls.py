import functools
import http.server
import shutil
import subprocess
import threading
import unittest
from pathlib import Path

import imageio_ffmpeg

from media_downloader.engine import DownloadEngine, DownloadRequest
from media_downloader.server import probe_media, sanitize_payload


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return


class LocalHlsIntegrationTest(unittest.TestCase):
    def test_downloads_and_remuxes_local_hls(self) -> None:
        root = Path.cwd() / ".test-hls"
        source = root / "source"
        output = root / "output"
        if root.exists():
            shutil.rmtree(root)
        source.mkdir(parents=True)
        output.mkdir(parents=True)

        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=duration=2:size=320x180:rate=10",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-hls_time",
                "0.5",
                "-hls_playlist_type",
                "vod",
                str(source / "stream.m3u8"),
            ],
            check=True,
        )

        handler = functools.partial(_QuietHandler, directory=str(source))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            probe = probe_media(sanitize_payload({"url": f"http://127.0.0.1:{port}/stream.m3u8"}))
            self.assertAlmostEqual(probe["duration"], 2.0, places=1)
            self.assertFalse(probe["live"])
            self.assertTrue(probe["thumbnail"].startswith("data:image/jpeg;base64,"))
            self.assertEqual((probe["width"], probe["height"]), (320, 180))
            request = DownloadRequest(
                url=f"http://127.0.0.1:{port}/stream.m3u8",
                output_dir=output,
                headers={"Referer": "https://player.example/watch"},
                filename_hint="Local HLS integration",
                expected_duration=2.0,
            )
            # The local HTTP server lives in this test process. The isolated
            # process path is covered separately by the locked-file cancellation test.
            engine = DownloadEngine(lambda _data: None, lambda _text: None, isolate_download=False)
            engine.download(request)
            files = list(output.glob("*.mp4"))
            self.assertEqual(len(files), 1)
            self.assertGreater(files[0].stat().st_size, 1_000)
            self.assertAlmostEqual(engine.media_duration(files[0]), 2.0, delta=0.2)
        finally:
            server.shutdown()
            server.server_close()
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()

