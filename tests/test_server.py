import json
import threading
import unittest
import urllib.error
import urllib.request

from media_downloader.server import CompanionServer, sanitize_prepare_payload


class PayloadTest(unittest.TestCase):
    def test_payload_keeps_only_safe_request_headers(self) -> None:
        result = sanitize_prepare_payload(
            {
                "url": "https://cdn.example/video.m3u8",
                "pageUrl": "https://example.test/watch",
                "title": "Episode 1",
                "sourceType": "captured_stream",
                "activeQualityConfirmed": True,
                "width": 1920,
                "height": 1080,
                "headers": {
                    "Origin": "https://player.example",
                    "Cookie": "session=test",
                    "Authorizations": "temporary-player-token",
                    "X-Playback-Session-Id": "session-id",
                    "Host": "attacker.example",
                    "Referer": "bad\r\nInjected: value",
                },
            }
        )
        self.assertEqual(result["headers"]["Origin"], "https://player.example")
        self.assertEqual(result["headers"]["Cookie"], "session=test")
        self.assertEqual(result["headers"]["Authorizations"], "temporary-player-token")
        self.assertEqual(result["headers"]["X-Playback-Session-Id"], "session-id")
        self.assertNotIn("Host", result["headers"])
        self.assertEqual(result["headers"]["Referer"], "https://example.test/watch")
        self.assertEqual(result["sourceType"], "captured_stream")
        self.assertTrue(result["activeQualityConfirmed"])
        self.assertEqual(result["height"], 1080)

    def test_payload_rejects_non_http_url(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_prepare_payload({"url": "file:///C:/secret.txt"})


class CompanionServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.received = []
        self.started = []
        self.signal = threading.Event()

        def callback(payload):
            self.received.append(payload)
            self.signal.set()

        self.server = CompanionServer(
            prepare_callback=callback,
            start_callback=lambda payload: self.started.append(payload),
            port=0,
            probe_callback=lambda _payload: {
                "duration": 1440.15,
                "live": False,
                "width": 1920,
                "height": 1080,
                "thumbnail": "",
            },
        )
        self.server.start()
        port = self.server._server.server_address[1]
        self.base = f"http://127.0.0.1:{port}"

    def tearDown(self) -> None:
        self.server.stop()

    def test_health_and_extension_prepare_does_not_start(self) -> None:
        with urllib.request.urlopen(f"{self.base}/health", timeout=2) as response:
            self.assertTrue(json.load(response)["ok"])

        body = json.dumps({"url": "https://cdn.example/active.m3u8", "title": "Test", "duration": 1420.5}).encode()
        request = urllib.request.Request(
            f"{self.base}/api/prepare",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Media-Helper": "1",
                "Origin": "chrome-extension://test-extension-id",
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 202)
        self.assertTrue(self.signal.wait(1))
        self.assertEqual(self.received[0]["url"], "https://cdn.example/active.m3u8")
        self.assertEqual(self.received[0]["duration"], 1420.5)
        self.assertEqual(self.started, [])

    def test_start_requires_job_id_and_download_endpoint_is_disabled(self) -> None:
        headers = {"Content-Type": "application/json", "X-Media-Helper": "1", "Origin": "chrome-extension://test"}
        request = urllib.request.Request(
            f"{self.base}/api/start", data=b'{"formatKey":"best"}', method="POST", headers=headers
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

        request = urllib.request.Request(
            f"{self.base}/api/download", data=b'{"url":"https://example.com/video"}', method="POST", headers=headers
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 409)
        caught.exception.close()

    def test_web_page_origin_is_rejected(self) -> None:
        request = urllib.request.Request(
            f"{self.base}/api/prepare",
            data=b'{"url":"https://cdn.example/video.m3u8"}',
            method="POST",
            headers={"X-Media-Helper": "1", "Origin": "https://malicious.example"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_probe_returns_media_metadata(self) -> None:
        body = json.dumps({"url": "https://cdn.example/active.m3u8"}).encode()
        request = urllib.request.Request(
            f"{self.base}/api/probe",
            data=body,
            method="POST",
            headers={"X-Media-Helper": "1", "Origin": "chrome-extension://test-extension-id"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            data = json.load(response)
        self.assertAlmostEqual(data["duration"], 1440.15)
        self.assertEqual(data["width"], 1920)


if __name__ == "__main__":
    unittest.main()
