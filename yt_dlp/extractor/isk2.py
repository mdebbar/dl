import json
import re
import string

import urllib.parse

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
)

WATCH_LABEL = 'مشاهدة الحلقة'

_HOSTS = '|'.join([
    # 'eceeq',
    '3isk',
    '3iskk',
    '3ick',
    '3esk',
    # 'esheaq',
])
_DOMAIN_RE = rf'https?://(?:\w{{1,4}}\.)?(?:{_HOSTS})\.(?:\w{{2,5}})'

_EPISODE_ID_RE = r'serie-(?P<series>[\w-]+?)-season-(?P<season>\d+)[\w\d-]*?-episode-(?P<episode>\d+)'

_EPISODE_URL_RE = rf'{_DOMAIN_RE}/watch/episodes/(?P<id>{_EPISODE_ID_RE})'

_HOME_URL_RE = rf'{_DOMAIN_RE}/?$'

# 20 minutes
_MIN_DURATION_SECONDS = 20 * 60


def _get_series_name(url):
    series = re.match(_EPISODE_URL_RE, url).group('series')
    # Remove extraneous suffixes like 25oct, etc.
    series = re.sub(r'-\d{1,2}[a-zA-Z]{2,4}\d{0,2}$', '', series)
    return string.capwords(series.replace('-', ' '))

class Isk2EpisodeIE(InfoExtractor):
    _VALID_URL = _EPISODE_URL_RE

    def _real_extract(self, url):
        video_id = self._match_id(url)

        # 1. Capture metadata using standard methods
        series = _get_series_name(url)

        mobj = self._match_valid_url(url)
        season_num = mobj.group('season').zfill(2)
        episode_num = mobj.group('episode').zfill(2)
        title = f'{series} {season_num}x{episode_num}'

        # 2. Use Playwright to extract the actual video URL
        self.write_debug(f'[{self.IE_NAME}] Launching browser to extract video URL for {video_id}...')
        captured = self._extract_with_playwright(url)

        if not captured['url']:
            raise ExtractorError('Playwright failed to capture the video URL', expected=True)

        self.to_screen(f'[{self.IE_NAME}] {title}')
        self.to_screen(f'[{self.IE_NAME}] -- {captured["url"]}')
        self.to_screen('-' * 40)

        # 3. Determine formats
        if '.m3u8' in captured["url"]:
            formats = self._extract_m3u8_formats(captured["url"], video_id, headers=captured['headers'])
        else:
            raise ExtractorError('Expected an m3u8 URL but got something else', expected=True)

        video_duration = self._extract_m3u8_vod_duration(formats[0]['url'], video_id)

        id = 'too-short' if video_duration < _MIN_DURATION_SECONDS else video_id

        return {
            'id': id,
            'title': title,
            'series': series,
            'season_number': int(season_num),
            'episode_number': int(episode_num),
            'formats': formats,
        }

    def _extract_with_playwright(self, url):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError('playwright is not installed. Run "pip install playwright && playwright install chromium"', expected=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            result = {"url": None, "headers": None}

            def handle_request(request):
                if (".m3u8" in request.url) and not result["url"]:
                    if "master.m3u8" in request.url or "playlist.m3u8" in request.url:
                        result["url"] = request.url
                        result["headers"] = request.headers

            page.on("request", handle_request)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # This listener will automatically close any ad tab that opens
                context.on("page", lambda new_page: new_page.close())

                watch_link = page.get_by_text(WATCH_LABEL)
                outer_iframe = page.frame_locator('#iframe_player')

                attempts = 0
                while attempts < 5:
                    # Click the button
                    watch_link.click(force=True, timeout=10000)
                    # Check if the video player (or next element) appeared
                    try:
                        outer_iframe.owner.wait_for(timeout=2000)
                        break
                    except:
                        attempts += 1

                if attempts == 5:
                    raise ExtractorError('Failed to click the watch button and load the video player', expected=True)

                # Now a thumbnail is shown with a play button overlay. Click the play button.
                inner_iframe = outer_iframe.locator('.Video').frame_locator('iframe')
                inner_iframe.owner.wait_for(timeout=100000)

                # Poll for the captured URL
                for _ in range(30):
                    if result["url"]:
                        break
                    page.wait_for_timeout(1000)

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                browser.close()

            return result


class Isk2HomeIE(InfoExtractor):
    _VALID_URL = _HOME_URL_RE
    IE_NAME = 'isk2:home'

    def _real_extract(self, url):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError('playwright is not installed. Run "pip install playwright && playwright install firefox"', expected=True)

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                episode_links = page.locator('.items-latest-eps a')

                entries = []
                for link in episode_links.all():
                    href = link.get_attribute('href')
                    try:
                        video_info = self.url_result(href, ie=Isk2EpisodeIE, video_id=re.match(_EPISODE_URL_RE, href).group('id'))
                        entries.append(video_info)
                    except Exception as e:
                        self.report_warning(f'Failed to process episode link {href}: {e}')

                print(json.dumps(entries[:3], indent=2))

                return self.playlist_result(entries[:3], playlist_id='3isk:home')

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                browser.close()

