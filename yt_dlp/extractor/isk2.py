import json
import re
import string

import urllib.parse

from .common import InfoExtractor
from ..utils import (
    ExtractorError,
)

_HALAKA = 'الحلقة'
_HALAKA_ENC = '%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9'
_MUSALSAL = 'مسلسل'
_MUSALSAL_ENC = '%d9%85%d8%b3%d9%84%d8%b3%d9%84'

_HOSTS = '|'.join([
    'krmzi',
])
_DOMAIN_RE = rf'https?://(?:\w{{1,4}}\.)?(?:{_HOSTS})\.(?:\w{{2,5}})'

_EPISODE_ID_RE = rf'{_MUSALSAL_ENC}-(?P<series>[^/]+?)-{_HALAKA_ENC}-(?P<episode>\d+)'

_EPISODE_URL_RE = rf'{_DOMAIN_RE}/episode/(?P<id>{_EPISODE_ID_RE})'
_HOME_URL_RE = rf'{_DOMAIN_RE}/?$'


class Isk2EpisodeIE(InfoExtractor):
    _VALID_URL = _EPISODE_URL_RE
    IE_NAME = 'isk2:episode'

    def _get_series_name(self, url):
        series = self._match_valid_url(url).group('series')
        series = urllib.parse.unquote(series)
        series = re.sub(rf'^{_MUSALSAL}-', '', series)
        series = re.sub(rf'-{_HALAKA}.*', '', series)
        return string.capwords(series.replace('-', ' '))

    def _real_extract(self, url):
        video_id = self._match_id(url)

        # 1. Capture metadata using standard methods
        series = self._get_series_name(url)

        mobj = self._match_valid_url(url)
        season_num = '01'
        episode_num = mobj.group('episode').zfill(2)
        title = f'{series} {season_num}x{episode_num}'

        # 2. Use Playwright to extract the actual video URL
        self.write_debug(f'[{self.IE_NAME}] Launching browser to extract video URL for {video_id}...')
        captured_url = self._extract_with_playwright(url)

        if not captured_url:
            raise ExtractorError('Playwright failed to capture the video URL', expected=True)

        self.to_screen(f'[{self.IE_NAME}] Successfully captured URL: {captured_url}')

        # 3. Determine formats
        if '.m3u8' in captured_url:
            formats = self._extract_m3u8_formats(captured_url, video_id, ext='mp4')
        else:
            formats = [{'url': captured_url}]

        return {
            'id': video_id,
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
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            captured_url = [None]

            def handle_request(request):
                if (".m3u8" in request.url or ".mp4" in request.url) and not captured_url[0]:
                    if "master.m3u8" in request.url or "playlist.m3u8" in request.url or ".mp4" in request.url:
                        captured_url[0] = request.url

            page.on("request", handle_request)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                embed_link = page.locator('.getEmbed a')
                if embed_link.count() > 0:
                    embed_link.first.click()
                    page.wait_for_load_state('domcontentloaded', timeout=60000)
                else:
                    raise ExtractorError('Could not find the embed link (.getEmbed a) on the page', expected=True)

                # Poll for the captured URL
                for _ in range(30):
                    if captured_url[0]:
                        break
                    page.wait_for_timeout(1000)

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                browser.close()

            return captured_url[0]


class Isk2HomeIE(InfoExtractor):
    _VALID_URL = _HOME_URL_RE
    IE_NAME = 'isk2:home'

    def _real_extract(self, url):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ExtractorError('playwright is not installed. Run "pip install playwright && playwright install chromium"', expected=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                episode_links = page.locator('article.post a')

                entries = []
                for link in episode_links.all():
                    href = link.get_attribute('href')
                    if not href:
                        continue
                    try:
                        video_info = self.url_result(href, ie=Isk2EpisodeIE)
                        entries.append(video_info)
                    except Exception as e:
                        self.report_warning(f'Failed to process episode link {href}: {e}')

                return self.playlist_result(entries[:1])

            except Exception as e:
                if isinstance(e, ExtractorError):
                    raise
                self.report_warning(f'Playwright error: {e}')
            finally:
                browser.close()

