"""Local integration checks: no credentials and no generation requests."""
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import serve_shared_preview as preview
import shared_download
import shared_video
from seedance_common import generation_lock


class QuietHandler(preview.Handler):
    def log_message(self, *args):
        pass


class PreviewTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name).resolve()
        cls.source = cls.root / 'fixture.mp4'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=640x360:rate=24', '-t', '2',
            '-c:v', 'libx264', '-crf', '0', '-preset', 'ultrafast',
            str(cls.source),
        ], check=True)
        cls.data = cls.source.read_bytes()
        assert len(cls.data) > 512 * 1024, 'Fixture must span multiple download chunks'
        cls.base_patch = patch.object(preview, 'BASE', cls.root)
        cls.base_patch.start()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.base_patch.stop()
        cls.temp.cleanup()

    def request(self, path, byte_range=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        conn.request('GET', path, headers={'Range': byte_range} if byte_range else {})
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return result

    def test_ranges_and_suffix_match_source_bytes(self):
        status, headers, body = self.request('/fixture.mp4', 'bytes=100-199')
        self.assertEqual(status, 206)
        self.assertEqual(body, self.data[100:200])
        self.assertEqual(headers['Content-Length'], '100')
        status, _, body = self.request('/fixture.mp4', 'bytes=-100')
        self.assertEqual(status, 206)
        self.assertEqual(body, self.data[-100:])
        self.assertEqual(self.request('/fixture.mp4', f'bytes={len(self.data)}-')[0], 416)

    def test_does_not_serve_files_outside_public_root(self):
        outside = self.root.parent / (self.root.name + '-private.txt')
        outside.write_text('not public')
        try:
            (self.root / 'escape.txt').symlink_to(outside)
            self.assertEqual(self.request('/escape.txt')[0], 403)
        finally:
            outside.unlink()

    def test_resume_and_assemble_multiple_chunks(self):
        target = self.root / 'download' / 'clip.mp4'
        parts = target.parent / 'download-parts'
        parts.mkdir(parents=True)
        # A prior interrupted transfer already saved part of its first chunk.
        (parts / '0.bin').write_bytes(self.data[:12345])
        url = f'http://127.0.0.1:{self.server.server_port}/fixture.mp4'
        shared_download.fetch(url, target)
        self.assertEqual(hashlib.sha256(target.read_bytes()).digest(),
                         hashlib.sha256(self.data).digest())


class SubmissionTests(unittest.TestCase):
    def test_lock_rejects_overlapping_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'worker.lock'
            with generation_lock(lock):
                with self.assertRaises(SystemExit):
                    with generation_lock(lock):
                        self.fail('Concurrent worker acquired the lock')
            with generation_lock(lock):
                pass

    def test_failed_or_uncertain_job_prevents_new_submissions(self):
        for outcome in ('failed', 'uncertain'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                job = root / 'jobs' / 'existing'
                job.mkdir(parents=True)
                if outcome == 'failed':
                    (job / 'task.json').write_text(json.dumps({'id': 'existing-task'}))
                else:
                    (job / 'submission-started.json').write_text('{}')
                (root / 'letterbox').mkdir()
                for year in (1800, 1825):
                    (root / f'letterbox/day-{year}.png').write_bytes(b'reference')
                segments = [{'id': 'existing', 'from': 1750, 'to': 1775},
                            {'id': 'new', 'from': 1800, 'to': 1825}]
                with patch.object(shared_video, 'OUT', root), \
                     patch.object(shared_video, 'manifest', return_value={'segments': segments}), \
                     patch.object(shared_video, 'load_auth', return_value={'key': 'test-only'}), \
                     patch.object(shared_video, 'request', return_value={'status': 'failed'}) as request, \
                     patch.object(shared_video.gengen, 'upload') as upload, \
                     patch('sys.argv', ['shared_video.py', '--submit']):
                    shared_video.main()
                    upload.assert_not_called()
                    self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list))
                    self.assertFalse((root / 'jobs/new/submission-started.json').exists())


if __name__ == '__main__':
    unittest.main()
