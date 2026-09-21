import fcntl
import json
import os
import re
import string
import time

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
    make_archive_id,
)

# TODO: Don't hardcode the `/app/downloads/` path
DOWNLOADS_PATH = os.environ.get('DOWNLOADS_PATH', '/app/downloads')
WATCH_LABEL = 'مشاهدة الحلقة'

_HOSTS = '|'.join([
    # 'eceeq',
    '3isk',
    '3iskk',
    '3ick',
    '3esk',
    'qisk',
    '3isktr',
    # 'esheaq',
])
_DOMAIN_RE = rf'https?://(?:\w{{1,4}}\.)?(?:{_HOSTS})\.(?:\w{{2,6}})'

_EPISODE_ID_RE = r'serie-(?P<series>[\w-]+?)-season-(?P<season>\d+)[\w\d-]*?-ep(?:isode|oside)?-(?P<episode>\d+)'

_EPISODE_URL_RE = rf'{_DOMAIN_RE}/watch/episodes/(?P<id>{_EPISODE_ID_RE})'

_HOME_URL_RE = rf'{_DOMAIN_RE}/?$'

# Baseline broadcast duration for complete Turkish drama episodes
_FULL_EPISODE_MIN_DURATION_SECONDS = 120 * 60

# 3isk sometimes publishes a short partial video before swapping in the full episode some time
# later. A fixed duration cutoff can't tell "genuinely short episode" apart from "still
# uploading", so instead:
#  - durations below this are rejected outright (ads/error pages, never a real episode)
_JUNK_DURATION_SECONDS = 15 * 60
#  - durations at or above this are trusted immediately, no waiting
_FAST_ACCEPT_DURATION_SECONDS = _FULL_EPISODE_MIN_DURATION_SECONDS
#  - anything in between is only accepted once the *same* duration has been seen on two
#    separate extractions spaced at least this far apart (i.e. it has stopped growing)
_STABILITY_WINDOW_SECONDS = 30 * 60

# Episodes accepted with duration below this are candidate partial uploads and will be re-probed
# on subsequent cron runs for up to _RECHECK_WINDOW_SECONDS to detect if the full episode arrives.
_SUSPICIOUS_SHORT_DURATION_SECONDS = _FULL_EPISODE_MIN_DURATION_SECONDS
_RECHECK_WINDOW_SECONDS = 48 * 3600  # 48 hours

# Retention and rotation to prevent long-term bloating
_STATE_RETENTION_SECONDS = 30 * 86400  # 30 days
_MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB

_DURATION_STATE_PATH = f'{DOWNLOADS_PATH}/.isk_duration_state.json'
_LOG_FILE_PATH = f'{DOWNLOADS_PATH}/isk_duration.log'

_FIREFOX_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
# _CHROME_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


def _format_duration(seconds):
    if seconds is None:
        return 'unknown'
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f'{hours}h {minutes:02d}m {secs:02d}s'
    return f'{minutes}m {secs:02d}s'


def _format_elapsed(seconds):
    if seconds is None:
        return 'unknown'
    seconds = int(max(0, seconds))
    minutes, secs = divmod(seconds, 60)
    if minutes >= 60:
        hours, mins = divmod(minutes, 60)
        return f'{hours}h {mins:02d}m {secs:02d}s'
    return f'{minutes}m {secs:02d}s'


def _get_series_name(url):
    series = re.match(_EPISODE_URL_RE, url).group('series')
    # Remove extraneous suffixes like 25oct, etc.
    series = re.sub(r'-\d{1,2}[a-zA-Z]{2,4}\d{0,2}$', '', series)
    return string.capwords(series.replace('-', ' '))


def _needs_duration_recheck(video_id):
    """True if this episode was recently accepted with a short duration and should be re-probed."""
    if not os.path.exists(_DURATION_STATE_PATH):
        return False
    try:
        with open(_DURATION_STATE_PATH, 'r', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            state = json.load(f)
        entry = state.get(video_id)
        if not isinstance(entry, dict):
            return False
        if entry.get('status') not in ('accepted_stable', 'accepted_fast'):
            return False
        accepted_dur = entry.get('accepted_duration') or 0
        if accepted_dur >= _SUSPICIOUS_SHORT_DURATION_SECONDS:
            return False
        now = time.time()
        accepted_at = entry.get('accepted_at') or entry.get('last_seen') or 0
        return (now - accepted_at) < _RECHECK_WINDOW_SECONDS
    except Exception:
        return False


def _remove_lines_from_archive(archive_file, lines_to_remove):
    """Atomically remove specified lines from an archive file under an exclusive file lock."""
    if not archive_file or not os.path.isfile(archive_file):
        return
    targets = set(lines_to_remove)
    try:
        with open(archive_file, 'r+', encoding='utf-8') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            lines = f.readlines()
            new_lines = [l for l in lines if l.strip() not in targets]
            if len(new_lines) != len(lines):
                f.seek(0)
                f.truncate()
                f.writelines(new_lines)
                f.flush()
    except OSError:
        pass


def _unarchive_video(downloader, video_id):
    """Remove video from in-memory archive and downloaded.txt file so yt-dlp re-downloads it."""
    archive_id = make_archive_id(IskEpisodeIE, video_id)
    if getattr(downloader, 'archive', None) is not None:
        downloader.archive.discard(archive_id)

    archive_file = downloader.params.get('download_archive')
    _remove_lines_from_archive(archive_file, [archive_id])


def _cleanup_state_and_logs(*, downloader=None):
    """Prune state entries older than 30 days, rotate logs if exceeding 5 MB, and clean legacy sentinels."""
    now = time.time()
    cutoff = now - _STATE_RETENTION_SECONDS

    # 1. State pruning
    if os.path.exists(_DURATION_STATE_PATH):
        try:
            with open(_DURATION_STATE_PATH, 'a+') as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.seek(0)
                try:
                    state = json.load(f)
                except (json.JSONDecodeError, OSError):
                    state = {}

                if isinstance(state, dict):
                    orig_len = len(state)
                    pruned_state = {
                        k: v for k, v in state.items()
                        if isinstance(v, dict) and v.get('last_seen', now) >= cutoff
                    }
                    if len(pruned_state) != orig_len:
                        f.seek(0)
                        f.truncate()
                        json.dump(pruned_state, f, indent=2)
                        f.flush()
        except OSError:
            pass

    # 2. Log rotation
    try:
        if os.path.exists(_LOG_FILE_PATH) and os.path.getsize(_LOG_FILE_PATH) >= _MAX_LOG_BYTES:
            rotated_path = f'{_LOG_FILE_PATH}.1'
            if os.path.exists(rotated_path):
                os.remove(rotated_path)
            os.replace(_LOG_FILE_PATH, rotated_path)
    except OSError:
        pass

    # 3. Clean legacy 'too-short' sentinel from archive file if present
    archive_file = (downloader.params.get('download_archive') if downloader else None) or f'{DOWNLOADS_PATH}/downloaded.txt'
    _remove_lines_from_archive(archive_file, ['iskepisode too-short'])


def _evaluate_and_record_duration(
    video_id,
    duration,
    *,
    title=None,
    series=None,
    webpage_url=None,
    m3u8_url=None,
    log_func=None,
    warn_func=None,
    downloader=None,
    info_dict=None,
):
    """Evaluate duration stability and persist full audit trail in state and log files."""
    now = time.time()
    now_iso = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))

    state_dir = os.path.dirname(_DURATION_STATE_PATH)
    if state_dir:
        os.makedirs(state_dir, exist_ok=True)

    with open(_DURATION_STATE_PATH, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            state = json.load(f)
            if not isinstance(state, dict):
                state = {}
        except (json.JSONDecodeError, OSError):
            state = {}

        entry = state.get(video_id)
        if not isinstance(entry, dict):
            entry = None

        if duration is None:
            status = 'rejected_no_duration'
            reason = 'VOD manifest duration could not be extracted (missing #EXT-X-ENDLIST or empty manifest)'
        elif entry and entry.get('status') in ('accepted_fast', 'accepted_stable'):
            status = entry['status']
            accepted_dur = entry.get('accepted_duration')
            if accepted_dur is not None and duration is not None and duration > accepted_dur:
                status = 'accepted_fast' if duration >= _FAST_ACCEPT_DURATION_SECONDS else 'accepted_stable'
                reason = (
                    f'Duration updated from {accepted_dur}s ({_format_duration(accepted_dur)}) to '
                    f'{duration}s ({_format_duration(duration)}); triggering re-download'
                )
                entry['accepted_duration'] = duration
                entry['accepted_duration_str'] = _format_duration(duration)
                entry['accepted_at'] = now
                entry['accepted_at_iso'] = now_iso
                entry['accepted_status'] = status
                entry['duration_changed_after_acceptance'] = True
                entry['post_acceptance_warning'] = reason
                if downloader:
                    _unarchive_video(downloader, video_id)
                    if hasattr(downloader, 'prepare_filename'):
                        try:
                            target_info = info_dict or {
                                'id': video_id,
                                'title': title,
                                'series': series,
                                'ext': 'mp4',
                            }
                            target_file = downloader.prepare_filename(target_info)
                            if target_file and os.path.isfile(target_file):
                                os.remove(target_file)
                            if target_file and os.path.isfile(f'{target_file}.part'):
                                os.remove(f'{target_file}.part')
                        except Exception:
                            pass
            elif accepted_dur is not None and accepted_dur != duration:
                reason = (
                    f'Previously accepted ({status}) at {entry.get("accepted_at_iso")} with duration '
                    f'{accepted_dur}s ({_format_duration(accepted_dur)}), but duration is now '
                    f'{duration}s ({_format_duration(duration)})'
                )
            else:
                reason = f'Already accepted ({status}) at {entry.get("accepted_at_iso")}'
        elif duration < _JUNK_DURATION_SECONDS:
            status = 'rejected_junk'
            reason = (
                f'Duration {duration}s ({_format_duration(duration)}) < '
                f'{_JUNK_DURATION_SECONDS}s junk threshold; rejected'
            )
        elif duration >= _FAST_ACCEPT_DURATION_SECONDS:
            status = 'accepted_fast'
            reason = (
                f'Duration {duration}s ({_format_duration(duration)}) >= '
                f'{_FAST_ACCEPT_DURATION_SECONDS}s fast-accept threshold; accepted immediately'
            )
        else:
            # Ambiguous range: stability window check
            if not entry:
                status = 'pending'
                reason = (
                    f'First observation at {duration}s ({_format_duration(duration)}); stability timer started '
                    f'(requires {_format_elapsed(_STABILITY_WINDOW_SECONDS)} unchanged)'
                )
            elif entry.get('last_duration') != duration:
                old_dur = entry.get('last_duration')
                status = 'pending'
                reason = (
                    f'Duration changed from {old_dur}s ({_format_duration(old_dur)}) to {duration}s '
                    f'({_format_duration(duration)}); stability timer reset'
                )
            else:
                first_seen = entry.get('first_seen', now)
                elapsed = now - first_seen
                if elapsed >= _STABILITY_WINDOW_SECONDS:
                    status = 'accepted_stable'
                    reason = (
                        f'Duration {duration}s ({_format_duration(duration)}) remained stable for '
                        f'{_format_elapsed(elapsed)} (>= {_format_elapsed(_STABILITY_WINDOW_SECONDS)} window); accepted'
                    )
                else:
                    status = 'pending'
                    reason = (
                        f'Duration {duration}s ({_format_duration(duration)}) unchanged, but elapsed '
                        f'{_format_elapsed(elapsed)} < {_format_elapsed(_STABILITY_WINDOW_SECONDS)} window; pending'
                    )

        is_pending = status in ('pending', 'rejected_junk', 'rejected_no_duration')

        if entry is None:
            entry = {
                'video_id': video_id,
                'first_seen': now,
                'first_seen_iso': now_iso,
                'checks_count': 0,
                'history': [],
            }

        # Reset stability timer if pending and duration changed
        if status == 'pending' and entry.get('last_duration') != duration:
            entry['first_seen'] = now
            entry['first_seen_iso'] = now_iso

        # Mark acceptance details when transitioning to accepted
        if status in ('accepted_fast', 'accepted_stable') and not entry.get('accepted_at'):
            entry['accepted_at'] = now
            entry['accepted_at_iso'] = now_iso
            entry['accepted_duration'] = duration
            entry['accepted_duration_str'] = _format_duration(duration)
            entry['accepted_status'] = status
            entry['accepted_reason'] = reason

        # Anomaly detection: duration changed after acceptance
        if entry.get('accepted_at') and entry.get('accepted_duration') != duration:
            entry['duration_changed_after_acceptance'] = True
            entry['post_acceptance_warning'] = reason

        if title:
            entry['title'] = title
        if series:
            entry['series'] = series
        if webpage_url:
            entry['webpage_url'] = webpage_url

        entry['last_seen'] = now
        entry['last_seen_iso'] = now_iso
        entry['last_duration'] = duration
        entry['last_duration_str'] = _format_duration(duration)
        entry['status'] = status
        entry['is_pending'] = is_pending
        entry['last_status_reason'] = reason
        entry['checks_count'] = entry.get('checks_count', 0) + 1

        history_item = {
            'timestamp': now,
            'timestamp_iso': now_iso,
            'duration': duration,
            'duration_str': _format_duration(duration),
            'status': status,
            'is_pending': is_pending,
            'reason': reason,
            'm3u8_url': m3u8_url,
        }
        history = entry.get('history')
        if not isinstance(history, list):
            history = []
        history.append(history_item)
        entry['history'] = history[-50:]

        state[video_id] = entry

        f.seek(0)
        f.truncate()
        json.dump(state, f, indent=2)
        f.flush()

    try:
        with open(_LOG_FILE_PATH, 'a', encoding='utf-8') as log_f:
            log_f.write(
                f'{now_iso} | [{status.upper()}] {video_id} | '
                f'duration={_format_duration(duration)} ({duration}s) | '
                f'checks={entry["checks_count"]} | '
                f'{reason}\n'
            )
    except OSError:
        pass

    if log_func:
        log_func(f'{video_id}: duration={_format_duration(duration)} ({duration}s), status={status} - {reason}')
    if warn_func and entry.get('duration_changed_after_acceptance'):
        warn_func(f'{video_id}: {entry["post_acceptance_warning"]}')

    return is_pending


class IskEpisodeIE(InfoExtractor):
    _VALID_URL = _EPISODE_URL_RE

    @classmethod
    def get_temp_id(cls, url):
        try:
            video_id = cls._match_id(url)
        except (IndexError, AttributeError):
            return None
        if _needs_duration_recheck(video_id):
            # Bypass early download-archive check to allow _real_extract to check
            # if 3isk updated this suspiciously short episode with a longer version.
            return None
        return video_id

    def _real_extract(self, url):
        video_id = self._match_id(url)

        # 1. Capture metadata using standard methods
        series = _get_series_name(url)

        mobj = self._match_valid_url(url)
        season_num = mobj.group('season').zfill(2)
        episode_num = mobj.group('episode').zfill(2)
        title = f'{series} {season_num}x{episode_num}'

        # 2. Use Playwright to extract the actual video URL
        captured = self._extract_with_playwright(url, video_id)

        if not captured['url']:
            raise ExtractorError('Failed to capture the video URL with Playwright', expected=True)

        # 3. Determine formats
        if '.m3u8' in captured['url']:
            formats = self._extract_m3u8_formats(captured['url'], video_id, headers=captured['headers'])
        else:
            raise ExtractorError('Expected an m3u8 URL but got something else', expected=True)

        video_duration = self._extract_m3u8_vod_duration(formats[0]['url'], video_id)

        info_dict = {
            'id': video_id,
            'title': title,
            'series': series,
            'season_number': int(season_num),
            'episode_number': int(episode_num),
            'duration': video_duration,
            'formats': formats,
            'ext': formats[0].get('ext', 'mp4') if formats else 'mp4',
        }

        is_pending = _evaluate_and_record_duration(
            video_id=video_id,
            duration=video_duration,
            title=title,
            series=series,
            webpage_url=url,
            m3u8_url=formats[0]['url'] if formats else None,
            log_func=self.to_screen,
            warn_func=self.report_warning,
            downloader=self._downloader,
            info_dict=info_dict,
        )

        info_dict['is_pending'] = is_pending
        return info_dict

    def _extract_with_playwright(self, url, video_id):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError('playwright is not installed. Run "pip install playwright"', expected=True)

        with sync_playwright() as p:
            start_time = time.perf_counter()
            browser = p.firefox.launch(headless=True)
            end_time = time.perf_counter()

            startup_duration = end_time - start_time
            self.write_debug(f'Firefox startup time: {startup_duration:.3f} seconds')

            context = browser.new_context(user_agent=_FIREFOX_USER_AGENT)
            page = context.new_page()

            result = {'url': None, 'headers': None}

            def _is_target_m3u8(request):
                return ('.m3u8' in request.url) and ('master.m3u8' in request.url or 'playlist.m3u8' in request.url)

            def handle_request(request):
                if not result['url'] and _is_target_m3u8(request):
                    result['url'] = request.url
                    result['headers'] = request.headers

            page.on('request', handle_request)

            try:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)

                # This listener will automatically close any ad tab that opens
                context.on('page', lambda new_page: new_page.close())

                watch_link = page.get_by_text(WATCH_LABEL, exact=True)
                outer_iframe = page.frame_locator('#iframe_player')

                attempts = 0
                while attempts < 5:
                    # Click the button
                    watch_link.click(force=True, timeout=10000)
                    # Check if the video player (or next element) appeared
                    try:
                        outer_iframe.owner.wait_for(timeout=2000)
                        break
                    except Exception:
                        attempts += 1

                if attempts == 5:
                    raise ExtractorError('Failed to click the watch button and load the video player', expected=True)

                # Wait for the inner player iframe to load and initiate stream playback
                inner_iframe = outer_iframe.locator('.Video').frame_locator('iframe')
                inner_iframe.owner.wait_for(timeout=10000)

                # Wait for m3u8 request event if not already captured
                if not result['url']:
                    try:
                        req = page.wait_for_event('request', predicate=_is_target_m3u8, timeout=30000)
                        result['url'] = req.url
                        result['headers'] = req.headers
                    except Exception:
                        pass

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                if not result['url']:
                    self._error_screenshot(page, video_id)
                browser.close()

            return result

    def _error_screenshot(self, page, video_id):
        file_path = f'{DOWNLOADS_PATH}/errors/{video_id}.png'
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.report_warning(f'See screenshot for details: {file_path}')
        page.screenshot(path=file_path, full_page=True)


class IskHomeIE(InfoExtractor):
    _VALID_URL = _HOME_URL_RE

    def _real_extract(self, url):
        _cleanup_state_and_logs(downloader=self._downloader)

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError('playwright is not installed. Run "pip install playwright && playwright install firefox"', expected=True)

        with sync_playwright() as p:
            start_time = time.perf_counter()
            browser = p.firefox.launch(headless=True)
            end_time = time.perf_counter()

            startup_duration = end_time - start_time
            self.write_debug(f'Firefox startup time: {startup_duration:.3f} seconds')

            context = browser.new_context(user_agent=_FIREFOX_USER_AGENT)
            page = context.new_page()

            try:
                page.goto(url, wait_until='load', timeout=60000)

                episode_links = page.locator('.items-latest-eps a')

                entries = []
                for link in episode_links.all():
                    href = link.get_attribute('href')
                    try:
                        video_info = self.url_result(href, ie=IskEpisodeIE, video_id=re.match(_EPISODE_URL_RE, href).group('id'))
                        entries.append(video_info)
                    except Exception as e:
                        self.report_warning(f'Failed to process episode link {href}: {e}')

                # Reverse the order so we download older videos first.
                return self.playlist_result(entries[::-1], playlist_id='3isk:home')

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                file_path = f'{DOWNLOADS_PATH}/home.latest.png'
                page.screenshot(path=file_path, full_page=True)
                browser.close()
