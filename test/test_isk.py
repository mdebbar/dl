#!/usr/bin/env python3

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp.extractor.isk as isk


class TestIskDurationState(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix='isk_test_')
        isk.DOWNLOADS_PATH = self.test_dir
        isk._DURATION_STATE_PATH = os.path.join(self.test_dir, '.isk_duration_state.json')
        isk._LOG_FILE_PATH = os.path.join(self.test_dir, 'isk_duration.log')

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_helpers(self):
        self.assertEqual(isk._format_duration(None), 'unknown')
        self.assertEqual(isk._format_duration(45), '0m 45s')
        self.assertEqual(isk._format_duration(2700), '45m 00s')
        self.assertEqual(isk._format_duration(6615), '1h 50m 15s')

        self.assertEqual(isk._format_elapsed(None), 'unknown')
        self.assertEqual(isk._format_elapsed(1800), '30m 00s')
        self.assertEqual(isk._format_elapsed(3665), '1h 01m 05s')

    def test_pending_to_stable_lifecycle(self):
        vid = 'serie-foo-season-01-episode-01'
        t0 = 1700000000.0

        orig_time = isk.time.time
        try:
            isk.time.time = lambda: t0

            # Check 1: first observation
            res1 = isk._evaluate_and_record_duration(
                vid,
                duration=2700,
                title='Foo 01x01',
                series='Foo',
                webpage_url='https://3isk.biz/watch/episodes/serie-foo-season-01-episode-01',
                m3u8_url='https://cdn.example.com/stream.m3u8',
            )
            self.assertEqual(res1, isk._PENDING_ID)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertIn(vid, state)
            entry = state[vid]
            self.assertEqual(entry['status'], 'pending')
            self.assertEqual(entry['checks_count'], 1)
            self.assertEqual(entry['last_duration'], 2700)
            self.assertEqual(len(entry['history']), 1)
            self.assertIsNone(entry.get('accepted_at'))

            # Check 2: 15 minutes later, duration unchanged -> still pending
            isk.time.time = lambda: t0 + 900
            res2 = isk._evaluate_and_record_duration(vid, duration=2700)
            self.assertEqual(res2, isk._PENDING_ID)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            self.assertEqual(entry['status'], 'pending')
            self.assertEqual(entry['checks_count'], 2)
            self.assertEqual(len(entry['history']), 2)

            # Check 3: 35 minutes after first_seen, duration unchanged -> accepted_stable
            isk.time.time = lambda: t0 + 2100
            res3 = isk._evaluate_and_record_duration(vid, duration=2700)
            self.assertEqual(res3, vid)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            # Key must NOT be deleted
            self.assertEqual(entry['status'], 'accepted_stable')
            self.assertEqual(entry['accepted_duration'], 2700)
            self.assertEqual(entry['accepted_status'], 'accepted_stable')
            self.assertEqual(entry['accepted_at'], t0 + 2100)
            self.assertEqual(entry['checks_count'], 3)
            self.assertEqual(len(entry['history']), 3)

            # Check 4: re-check after acceptance with changed duration
            warnings = []
            isk.time.time = lambda: t0 + 7200
            res4 = isk._evaluate_and_record_duration(
                vid,
                duration=7800,
                warn_func=warnings.append,
            )
            self.assertEqual(res4, vid)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            self.assertTrue(entry.get('duration_changed_after_acceptance'))
            self.assertEqual(entry['accepted_duration'], 7800)
            self.assertEqual(entry['last_duration'], 7800)
            self.assertEqual(entry['checks_count'], 4)
            self.assertEqual(len(entry['history']), 4)
            self.assertTrue(any('Duration updated' in w for w in warnings))

        finally:
            isk.time.time = orig_time

        # Verify log file has entries
        with open(isk._LOG_FILE_PATH) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 4)
        self.assertIn('[PENDING]', lines[0])
        self.assertIn('[ACCEPTED_STABLE]', lines[2])

    def test_duration_change_resets_pending_timer(self):
        vid = 'serie-bar-season-01-episode-02'
        orig_time = isk.time.time
        t0 = 1700000000.0

        try:
            isk.time.time = lambda: t0
            res1 = isk._evaluate_and_record_duration(vid, duration=1800)
            self.assertEqual(res1, isk._PENDING_ID)

            # 20 minutes later, duration increases from 1800 to 2400
            isk.time.time = lambda: t0 + 1200
            res2 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertEqual(res2, isk._PENDING_ID)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            self.assertEqual(entry['first_seen'], t0 + 1200)

            # 25 minutes after reset (t0 + 2700), still under 30m window
            isk.time.time = lambda: t0 + 2700
            res3 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertEqual(res3, isk._PENDING_ID)

            # 35 minutes after reset (t0 + 3300), now stable
            isk.time.time = lambda: t0 + 3300
            res4 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertEqual(res4, vid)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertEqual(state[vid]['status'], 'accepted_stable')
            self.assertEqual(state[vid]['accepted_duration'], 2400)
        finally:
            isk.time.time = orig_time

    def test_fast_accept(self):
        vid = 'serie-baz-season-01-episode-03'
        res = isk._evaluate_and_record_duration(vid, duration=7500)
        self.assertEqual(res, vid)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'accepted_fast')
        self.assertEqual(entry['accepted_duration'], 7500)
        self.assertEqual(entry['checks_count'], 1)

    def test_rejected_junk(self):
        vid = 'serie-junk-season-01-episode-04'
        res = isk._evaluate_and_record_duration(vid, duration=600)
        self.assertEqual(res, isk._PENDING_ID)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'rejected_junk')
        self.assertEqual(entry['checks_count'], 1)

    def test_rejected_no_duration(self):
        vid = 'serie-nodur-season-01-episode-05'
        res = isk._evaluate_and_record_duration(vid, duration=None)
        self.assertEqual(res, isk._PENDING_ID)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'rejected_no_duration')

    def test_needs_duration_recheck_and_get_temp_id(self):
        url = 'https://3isk.biz/watch/episodes/serie-test-season-01-episode-10'
        vid = 'serie-test-season-01-episode-10'

        # Case 1: Video not in state -> get_temp_id returns vid
        self.assertFalse(isk._needs_duration_recheck(vid))
        self.assertEqual(isk.IskEpisodeIE.get_temp_id(url), vid)

        # Case 2: Video accepted with full duration (125m >= 120m threshold) -> no recheck
        isk._evaluate_and_record_duration(vid, duration=7500)
        self.assertFalse(isk._needs_duration_recheck(vid))
        self.assertEqual(isk.IskEpisodeIE.get_temp_id(url), vid)

        # Case 3: Video accepted with short duration (30m) within 48h -> needs recheck!
        vid2 = 'serie-short-season-01-episode-11'
        url2 = 'https://3isk.biz/watch/episodes/serie-short-season-01-episode-11'
        orig_time = isk.time.time
        t0 = 1700000000.0
        try:
            isk.time.time = lambda: t0
            isk._evaluate_and_record_duration(vid2, duration=1800)
            isk.time.time = lambda: t0 + 2000  # become stable
            isk._evaluate_and_record_duration(vid2, duration=1800)

            # Check within 24h
            isk.time.time = lambda: t0 + 3600
            self.assertTrue(isk._needs_duration_recheck(vid2))
            # get_temp_id returns None to bypass archive check!
            self.assertIsNone(isk.IskEpisodeIE.get_temp_id(url2))

            # Case 4: Video accepted with short duration but > 48h ago -> no recheck
            isk.time.time = lambda: t0 + (49 * 3600)
            self.assertFalse(isk._needs_duration_recheck(vid2))
            self.assertEqual(isk.IskEpisodeIE.get_temp_id(url2), vid2)
        finally:
            isk.time.time = orig_time

    def test_unarchive_on_duration_growth(self):
        vid = 'serie-grow-season-01-episode-12'
        archive_file = os.path.join(self.test_dir, 'downloaded.txt')
        with open(archive_file, 'w') as f:
            f.write(f'iskepisode {vid}\n')
            f.write('iskepisode other-ep\n')

        class MockDownloader:
            def __init__(self):
                self.params = {'download_archive': archive_file}
                self.archive = {f'iskepisode {vid}', 'iskepisode other-ep'}

        mock_dl = MockDownloader()

        orig_time = isk.time.time
        t0 = 1700000000.0
        try:
            isk.time.time = lambda: t0
            isk._evaluate_and_record_duration(vid, duration=1800, series='GrowSeries', title='GrowSeries 01x12')
            isk.time.time = lambda: t0 + 2000
            isk._evaluate_and_record_duration(vid, duration=1800, series='GrowSeries', title='GrowSeries 01x12')

            # Recheck: duration grows to 7500s (125m)
            isk.time.time = lambda: t0 + 5000
            res = isk._evaluate_and_record_duration(
                vid,
                duration=7500,
                series='GrowSeries',
                title='GrowSeries 01x12',
                downloader=mock_dl,
            )
            self.assertEqual(res, vid)

            # Must be un-archived from memory and file
            self.assertNotIn(f'iskepisode {vid}', mock_dl.archive)
            with open(archive_file) as f:
                lines = f.read().splitlines()
            self.assertNotIn(f'iskepisode {vid}', lines)
            self.assertIn('iskepisode other-ep', lines)

            # Overwrites must be enabled for native yt-dlp handling
            self.assertTrue(mock_dl.params.get('overwrites'))

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertEqual(state[vid]['accepted_duration'], 7500)
            self.assertEqual(state[vid]['status'], 'accepted_fast')
        finally:
            isk.time.time = orig_time

    def test_state_pruning_30_days(self):
        t0 = 1700000000.0
        orig_time = isk.time.time
        try:
            # Seed state file with old entry (35 days old) and recent entry (10 days old)
            old_entry = {
                'video_id': 'old-ep',
                'status': 'accepted_fast',
                'last_seen': t0 - (35 * 86400),
            }
            recent_entry = {
                'video_id': 'recent-ep',
                'status': 'accepted_fast',
                'last_seen': t0 - (10 * 86400),
            }
            with open(isk._DURATION_STATE_PATH, 'w') as f:
                json.dump({'old-ep': old_entry, 'recent-ep': recent_entry}, f)

            isk.time.time = lambda: t0
            isk._evaluate_and_record_duration('new-ep', duration=7500)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)

            self.assertNotIn('old-ep', state)
            self.assertIn('recent-ep', state)
            self.assertIn('new-ep', state)
        finally:
            isk.time.time = orig_time

    def test_log_rotation_5mb(self):
        # Create log file slightly larger than 5 MB
        pad_size = isk._MAX_LOG_BYTES + 100
        with open(isk._LOG_FILE_PATH, 'wb') as f:
            f.write(b'x' * pad_size)

        isk._evaluate_and_record_duration('rotate-ep', duration=7500)

        # Main log file was rotated to .1 and new file started
        rotated_path = f'{isk._LOG_FILE_PATH}.1'
        self.assertTrue(os.path.isfile(rotated_path))
        self.assertEqual(os.path.getsize(rotated_path), pad_size)

        self.assertTrue(os.path.isfile(isk._LOG_FILE_PATH))
        self.assertLess(os.path.getsize(isk._LOG_FILE_PATH), 1024)
        with open(isk._LOG_FILE_PATH, 'r') as f:
            content = f.read()
        self.assertIn('rotate-ep', content)


if __name__ == '__main__':
    unittest.main()
