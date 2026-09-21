#!/usr/bin/env python3

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yt_dlp.extractor.isk as isk
from test.helper import FakeYDL


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

            # Check 1: first observation -> is_pending is True
            res1 = isk._evaluate_and_record_duration(
                vid,
                duration=2700,
                title='Foo 01x01',
                series='Foo',
                webpage_url='https://3isk.biz/watch/episodes/serie-foo-season-01-episode-01',
                m3u8_url='https://cdn.example.com/stream.m3u8',
            )
            self.assertTrue(res1)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertIn(vid, state)
            entry = state[vid]
            self.assertEqual(entry['status'], 'pending')
            self.assertTrue(entry['is_pending'])
            self.assertEqual(entry['checks_count'], 1)
            self.assertEqual(entry['last_duration'], 2700)
            self.assertEqual(len(entry['history']), 1)
            self.assertIsNone(entry.get('accepted_at'))

            # Check 2: 15 minutes later, duration unchanged -> still pending
            isk.time.time = lambda: t0 + 900
            res2 = isk._evaluate_and_record_duration(vid, duration=2700)
            self.assertTrue(res2)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            self.assertEqual(entry['status'], 'pending')
            self.assertTrue(entry['is_pending'])
            self.assertEqual(entry['checks_count'], 2)
            self.assertEqual(len(entry['history']), 2)

            # Check 3: 35 minutes after first_seen, duration unchanged -> accepted_stable
            isk.time.time = lambda: t0 + 2100
            res3 = isk._evaluate_and_record_duration(vid, duration=2700)
            self.assertFalse(res3)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            # Key must NOT be deleted
            self.assertEqual(entry['status'], 'accepted_stable')
            self.assertFalse(entry['is_pending'])
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
            self.assertFalse(res4)

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
            self.assertTrue(res1)

            # 20 minutes later, duration increases from 1800 to 2400
            isk.time.time = lambda: t0 + 1200
            res2 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertTrue(res2)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            entry = state[vid]
            self.assertEqual(entry['first_seen'], t0 + 1200)

            # 25 minutes after reset (t0 + 2700), still under 30m window
            isk.time.time = lambda: t0 + 2700
            res3 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertTrue(res3)

            # 35 minutes after reset (t0 + 3300), now stable
            isk.time.time = lambda: t0 + 3300
            res4 = isk._evaluate_and_record_duration(vid, duration=2400)
            self.assertFalse(res4)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertEqual(state[vid]['status'], 'accepted_stable')
            self.assertFalse(state[vid]['is_pending'])
            self.assertEqual(state[vid]['accepted_duration'], 2400)
        finally:
            isk.time.time = orig_time

    def test_fast_accept(self):
        vid = 'serie-baz-season-01-episode-03'
        res = isk._evaluate_and_record_duration(vid, duration=7500)
        self.assertFalse(res)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'accepted_fast')
        self.assertFalse(entry['is_pending'])
        self.assertEqual(entry['accepted_duration'], 7500)
        self.assertEqual(entry['checks_count'], 1)

    def test_rejected_junk(self):
        vid = 'serie-junk-season-01-episode-04'
        res = isk._evaluate_and_record_duration(vid, duration=600)
        self.assertTrue(res)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'rejected_junk')
        self.assertTrue(entry['is_pending'])
        self.assertEqual(entry['checks_count'], 1)

    def test_rejected_no_duration(self):
        vid = 'serie-nodur-season-01-episode-05'
        res = isk._evaluate_and_record_duration(vid, duration=None)
        self.assertTrue(res)

        with open(isk._DURATION_STATE_PATH) as f:
            state = json.load(f)
        entry = state[vid]
        self.assertEqual(entry['status'], 'rejected_no_duration')
        self.assertTrue(entry['is_pending'])

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

        target_file = os.path.join(self.test_dir, 'GrowSeries 01x12.mp4')
        with open(target_file, 'w') as f:
            f.write('dummy existing video content')

        class MockDownloader:
            def __init__(self):
                self.params = {'download_archive': archive_file}
                self.archive = {f'iskepisode {vid}', 'iskepisode other-ep'}
                self.prepared_info = None

            def prepare_filename(self, info_dict):
                self.prepared_info = info_dict
                return target_file

        mock_dl = MockDownloader()

        orig_time = isk.time.time
        t0 = 1700000000.0
        try:
            isk.time.time = lambda: t0
            isk._evaluate_and_record_duration(vid, duration=1800, series='GrowSeries', title='GrowSeries 01x12')
            isk.time.time = lambda: t0 + 2000
            isk._evaluate_and_record_duration(vid, duration=1800, series='GrowSeries', title='GrowSeries 01x12')

            # Recheck: duration grows to 7500s (125m)
            full_info = {
                'id': vid,
                'series': 'GrowSeries',
                'title': 'GrowSeries 01x12',
                'season_number': 1,
                'episode_number': 12,
                'duration': 7500,
                'ext': 'mp4',
            }
            isk.time.time = lambda: t0 + 5000
            res = isk._evaluate_and_record_duration(
                vid,
                duration=7500,
                series='GrowSeries',
                title='GrowSeries 01x12',
                downloader=mock_dl,
                info_dict=full_info,
            )
            self.assertFalse(res)

            # Must be un-archived from memory and file
            self.assertNotIn(f'iskepisode {vid}', mock_dl.archive)
            with open(archive_file) as f:
                lines = f.read().splitlines()
            self.assertNotIn(f'iskepisode {vid}', lines)
            self.assertIn('iskepisode other-ep', lines)

            # Target file on disk must be removed for clean re-download
            self.assertFalse(os.path.exists(target_file))
            self.assertEqual(mock_dl.prepared_info, full_info)

            # Overwrites parameter must NOT be mutated globally
            self.assertNotIn('overwrites', mock_dl.params)

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertEqual(state[vid]['accepted_duration'], 7500)
            self.assertEqual(state[vid]['status'], 'accepted_fast')
            self.assertFalse(state[vid]['is_pending'])
        finally:
            isk.time.time = orig_time

    def test_cleanup_state_and_logs(self):
        t0 = 1700000000.0
        orig_time = isk.time.time
        try:
            # 1. Test 30-day state pruning
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

            # 2. Test 5 MB log rotation
            pad_size = isk._MAX_LOG_BYTES + 100
            with open(isk._LOG_FILE_PATH, 'wb') as f:
                f.write(b'x' * pad_size)

            # 3. Test legacy 'too-short' removal from archive
            archive_file = os.path.join(self.test_dir, 'downloaded.txt')
            with open(archive_file, 'w') as f:
                f.write('iskepisode too-short\n')
                f.write('iskepisode valid-ep-1\n')

            class MockDownloader:
                def __init__(self):
                    self.params = {'download_archive': archive_file}

            isk.time.time = lambda: t0
            isk._cleanup_state_and_logs(downloader=MockDownloader())

            with open(isk._DURATION_STATE_PATH) as f:
                state = json.load(f)
            self.assertNotIn('old-ep', state)
            self.assertIn('recent-ep', state)

            rotated_path = f'{isk._LOG_FILE_PATH}.1'
            self.assertTrue(os.path.isfile(rotated_path))
            self.assertEqual(os.path.getsize(rotated_path), pad_size)
            self.assertFalse(os.path.exists(isk._LOG_FILE_PATH))

            with open(archive_file) as f:
                archive_lines = f.read().splitlines()
            self.assertNotIn('iskepisode too-short', archive_lines)
            self.assertIn('iskepisode valid-ep-1', archive_lines)
        finally:
            isk.time.time = orig_time

    def test_match_filter_integration(self):
        from yt_dlp.utils import match_filter_func

        mf = match_filter_func(['!is_pending'])

        pending_info = {'id': 'ep-pending', 'title': 'Ep Pending', 'is_pending': True}
        accepted_info = {'id': 'ep-accepted', 'title': 'Ep Accepted', 'is_pending': False}
        other_info = {'id': 'ep-other', 'title': 'Ep Other'}

        # Pending episode is rejected by the filter
        self.assertIsNotNone(mf(pending_info))
        self.assertIn('does not pass filter', mf(pending_info))

        # Accepted episode passes
        self.assertIsNone(mf(accepted_info))

        # Other extractors without is_pending pass
        self.assertIsNone(mf(other_info))


class MockPage:
    def __init__(self):
        self.is_closed = False
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def goto(self, url, **kwargs):
        pass

    def get_by_text(self, text, **kwargs):
        return MagicMock()

    def frame_locator(self, selector):
        return MagicMock()

    def locator(self, selector):
        loc = MagicMock()
        loc.all.return_value = []
        return loc

    def wait_for_event(self, event, **kwargs):
        req = MagicMock()
        req.url = 'https://cdn.example.com/stream/master.m3u8'
        req.headers = {'User-Agent': 'test'}
        return req

    def screenshot(self, **kwargs):
        pass

    def close(self):
        self.is_closed = True


class MockContext:
    def __init__(self, user_agent=None):
        self.user_agent = user_agent
        self.is_closed = False
        self.pages = []
        self.listeners = {}

    def new_page(self):
        p = MockPage()
        self.pages.append(p)
        return p

    def on(self, event, handler):
        self.listeners[event] = handler

    def close(self):
        self.is_closed = True
        for p in self.pages:
            p.close()


class MockBrowser:
    def __init__(self):
        self._connected = True
        self.contexts = []

    def is_connected(self):
        return self._connected

    def new_context(self, user_agent=None):
        ctx = MockContext(user_agent=user_agent)
        self.contexts.append(ctx)
        return ctx

    def close(self):
        self._connected = False
        for c in self.contexts:
            c.close()


class MockPlaywright:
    def __init__(self):
        self.firefox = MagicMock()
        self.launch_count = 0
        self.browsers = []
        self.is_stopped = False

        def mock_launch(**kwargs):
            self.launch_count += 1
            b = MockBrowser()
            self.browsers.append(b)
            return b

        self.firefox.launch.side_effect = mock_launch

    def stop(self):
        self.is_stopped = True


class TestPlaywrightBrowserPool(unittest.TestCase):
    def test_lazy_initialization(self):
        pool = isk.PlaywrightBrowserPool()
        try:
            state = pool._get_thread_state()
            self.assertIsNone(state.browser)
            self.assertIsNone(state.playwright)
            self.assertEqual(state.use_count, 0)
        finally:
            pool.close_all()

    def test_reuse_across_extractions(self):
        mock_p = MockPlaywright()
        with patch.dict(sys.modules, {'playwright.sync_api': MagicMock(sync_playwright=lambda: MagicMock(start=lambda: mock_p))}):
            pool = isk.PlaywrightBrowserPool()
            try:
                # Borrow 1
                with pool.borrow_page(user_agent='UA-1') as (ctx1, page1):
                    self.assertFalse(ctx1.is_closed)
                    self.assertFalse(page1.is_closed)
                    self.assertEqual(ctx1.user_agent, 'UA-1')
                self.assertTrue(ctx1.is_closed)
                self.assertTrue(page1.is_closed)
                self.assertEqual(mock_p.launch_count, 1)

                # Borrow 2 (reuses existing Firefox browser)
                with pool.borrow_page(user_agent='UA-2') as (ctx2, page2):
                    self.assertFalse(ctx2.is_closed)
                    self.assertFalse(page2.is_closed)
                    self.assertEqual(ctx2.user_agent, 'UA-2')
                    self.assertIsNot(ctx1, ctx2)
                self.assertTrue(ctx2.is_closed)
                self.assertTrue(page2.is_closed)

                # Browser was NOT launched a second time
                self.assertEqual(mock_p.launch_count, 1)
                self.assertEqual(len(mock_p.browsers), 1)
                self.assertTrue(mock_p.browsers[0].is_connected())
            finally:
                pool.close_all()
                self.assertTrue(mock_p.is_stopped)
                self.assertFalse(mock_p.browsers[0].is_connected())

    def test_context_closed_on_exception(self):
        mock_p = MockPlaywright()
        with patch.dict(sys.modules, {'playwright.sync_api': MagicMock(sync_playwright=lambda: MagicMock(start=lambda: mock_p))}):
            pool = isk.PlaywrightBrowserPool()
            try:
                with self.assertRaises(RuntimeError):
                    with pool.borrow_page() as (ctx, page):
                        raise RuntimeError('Extraction failed midway')
                self.assertTrue(ctx.is_closed)
                self.assertTrue(page.is_closed)
                self.assertEqual(mock_p.launch_count, 1)
                self.assertTrue(mock_p.browsers[0].is_connected())
            finally:
                pool.close_all()

    def test_auto_recovery_on_disconnect(self):
        mock_p = MockPlaywright()
        with patch.dict(sys.modules, {'playwright.sync_api': MagicMock(sync_playwright=lambda: MagicMock(start=lambda: mock_p))}):
            pool = isk.PlaywrightBrowserPool()
            try:
                with pool.borrow_page():
                    pass
                self.assertEqual(mock_p.launch_count, 1)

                # Simulate browser crash / disconnect
                mock_p.browsers[0]._connected = False

                # Subsequent borrow automatically re-launches browser
                with pool.borrow_page():
                    pass
                self.assertEqual(mock_p.launch_count, 2)
                self.assertEqual(len(mock_p.browsers), 2)
                self.assertTrue(mock_p.browsers[1].is_connected())
            finally:
                pool.close_all()

    def test_max_uses_recycling(self):
        mock_p = MockPlaywright()
        with patch.dict(sys.modules, {'playwright.sync_api': MagicMock(sync_playwright=lambda: MagicMock(start=lambda: mock_p))}):
            pool = isk.PlaywrightBrowserPool(max_uses=2)
            try:
                with pool.borrow_page():
                    pass
                self.assertEqual(mock_p.launch_count, 1)

                with pool.borrow_page():
                    pass
                self.assertEqual(mock_p.launch_count, 1)

                # Third borrow exceeds max_uses=2, triggers fresh launch
                with pool.borrow_page():
                    pass
                self.assertEqual(mock_p.launch_count, 2)
            finally:
                pool.close_all()

    def test_missing_playwright_raises_extractor_error(self):
        with patch.dict(sys.modules, {'playwright': None, 'playwright.sync_api': None}):
            pool = isk.PlaywrightBrowserPool()
            try:
                with self.assertRaises(isk.ExtractorError) as cm:
                    pool.get_browser()
                self.assertTrue(cm.exception.expected)
                self.assertIn('playwright is not installed', str(cm.exception))
            finally:
                pool.close_all()

    def test_integration_browser_reuse_across_home_and_episodes(self):
        mock_p = MockPlaywright()
        with patch.dict(sys.modules, {'playwright.sync_api': MagicMock(sync_playwright=lambda: MagicMock(start=lambda: mock_p))}):
            orig_pool = isk._BROWSER_POOL
            test_pool = isk.PlaywrightBrowserPool()
            isk._BROWSER_POOL = test_pool
            try:
                ydl = FakeYDL()
                # 1. Home page extraction
                home_ie = isk.IskHomeIE(ydl)
                with patch.object(isk.IskHomeIE, 'playlist_result', return_value={'_type': 'playlist', 'entries': []}):
                    home_ie._real_extract('https://3isk.biz/')
                self.assertEqual(mock_p.launch_count, 1)

                # 2. Episode 1 extraction
                ep_ie = isk.IskEpisodeIE(ydl)
                with patch.object(isk.IskEpisodeIE, '_extract_m3u8_formats', return_value=[{'url': 'https://cdn.example.com/master.m3u8', 'ext': 'mp4'}]):
                    with patch.object(isk.IskEpisodeIE, '_extract_m3u8_vod_duration', return_value=7500):
                        info1 = ep_ie._real_extract('https://3isk.biz/watch/episodes/serie-alpha-season-01-episode-01')
                # Browser is REUSED: launch_count remains 1
                self.assertEqual(mock_p.launch_count, 1)
                self.assertEqual(info1['id'], 'serie-alpha-season-01-episode-01')

                # 3. Episode 2 extraction
                with patch.object(isk.IskEpisodeIE, '_extract_m3u8_formats', return_value=[{'url': 'https://cdn.example.com/master.m3u8', 'ext': 'mp4'}]):
                    with patch.object(isk.IskEpisodeIE, '_extract_m3u8_vod_duration', return_value=7500):
                        info2 = ep_ie._real_extract('https://3isk.biz/watch/episodes/serie-alpha-season-01-episode-02')
                # Browser is STILL REUSED: launch_count remains 1
                self.assertEqual(mock_p.launch_count, 1)
                self.assertEqual(info2['id'], 'serie-alpha-season-01-episode-02')
            finally:
                test_pool.close_all()
                isk._BROWSER_POOL = orig_pool


if __name__ == '__main__':
    unittest.main()
