import re
import string
import urllib.parse

from .common import (
    ExtractorError,
    InfoExtractor,
)
from ..utils import (
    extract_attributes,
    get_element_by_class,
    get_elements_by_class,
    get_elements_html_by_class,
    traverse_obj,
    unescapeHTML,
)

# الحلقة
_AL_HALAKA = '%d8%a7%d9%84%d8%ad%d9%84%d9%82%d8%a9'

_DOMAIN_RE = r'https?://(?:\w{1,4}\.)?aradra?ma?tv\.(?:\w{2,4})'


_EPISODE_ID_RE = r'(?P<series>[^/]+?)-' + _AL_HALAKA + r'-(?P<episode>\d+)'

_SERIES_URL_RE = rf'{_DOMAIN_RE}/\d+/\d+/(?P<id>[^/]+)'
_EPISODE_LIST_URL_RE = rf'{_DOMAIN_RE}/category/episodes/([\w-]+/)?[\w-]+/(?P<id>[^/"<>]+)(/page/\d+)?'
_EPISODE_URL_RE = rf'{_DOMAIN_RE}/\d+/\d+/(?P<id>{_EPISODE_ID_RE})'


class AradramaBaseIE(InfoExtractor):
    def _download_with_referer(self, url, video_id, note, referer, data=None):
        return self._download_webpage(
            url,
            video_id,
            note,
            headers={'Referer': referer},
            data=data,
        )

    def _find_supported_cdns(self, cdn_links, video_id):
        supported_cdns = [
            'ok.ru',
            'vk.com',
            'rubyvid',
            'vidmoly',
            'uqload',


            # Not supported:
            # 'luluvdo',
            # 'vidhide',
            # 'dood.li',
            # 'swdyu.com',
            # 'filemoon',
            # 'streamtape',
            # 'upstream.to',
            # 'mixdrop',
            # 'vadbam',
            # 'playerwish',

            # EASY, HAS DIRECT MP4 LINK:
            # 'vdbtm',

            # EASY, HAS DIRECT M3U8 LINK:
            # '1vid1shar',
        ]

        found = False
        for supported in supported_cdns:
            for link in cdn_links:
                if supported in link:
                    found = True
                    yield link

        if not found:
            raise ExtractorError('Could not find a link to a supported CDN', video_id=video_id)

    def _try_server_links(self, server_links, video_id, referer):
        for iframe_url in self._find_supported_cdns(server_links, video_id):
            iframe_html = self._download_with_referer(
                iframe_url,
                video_id,
                f'Downloading video iframe {iframe_url}',
                referer,
            )

            self.debug('IFRAME CDN URL', iframe_url)
            self.debug('IFRAME HTML', iframe_html)

            # rubyvid
            # vidmoly
            mobj = re.search(r'file:\s*([\'"])(?P<url>https?://.*?\.m3u8[^\'"]*)\1', iframe_html)
            if mobj:
                m3u8_url = mobj.group('url')
                return m3u8_url, iframe_url

            # ok.ru
            mobj = re.search(r'data-options="(?P<dataoptions>[^"]+)"', iframe_html)
            if mobj:
                try:
                    data_options = self._parse_json(unescapeHTML(mobj.group('dataoptions')), video_id)
                    metadata = self._parse_json(data_options['flashvars']['metadata'], video_id)
                    m3u8_url = metadata['hlsManifestUrl']
                    return m3u8_url, iframe_url
                except Exception:
                    pass

            # vk.com
            try:
                player_params = self._search_json(
                    r'playerParams\s*=',
                    iframe_html,
                    'playerParams',
                    video_id,
                )
                m3u8_url = traverse_obj(player_params, ('params', 0, 'hls'))
                if m3u8_url:
                    return m3u8_url, iframe_url
            except Exception:
                pass

            # uqload
            try:
                mobj = re.search(r'([\'"])(?P<mp4_url>https?://[^\'"]*uqload[^\'"]*\.mp4)\1', iframe_html)
                if mobj:
                    return mobj.group('mp4_url'), iframe_url
            except Exception:
                pass

            self.to_screen(f'Could not find m3u8 URL in iframe {iframe_url}')

        raise ExtractorError('Could not find an m3u8 URL in any of the server links', video_id=video_id)

    def debug(self, name, info):
        self.write_debug('\n')
        self.write_debug('=' * 20)
        self.write_debug('\n')
        self.write_debug(f'{name}:\n')
        self.write_debug(info)
        self.write_debug('\n')


class AradramaEpisodeIE(AradramaBaseIE):
    _VALID_URL = _EPISODE_URL_RE

    def _real_extract(self, url):
        video_id = urllib.parse.unquote(self._match_id(url))

        webpage = self._download_webpage(url, video_id)

        self.debug('INITIAL WEB PAGE', webpage)

        mobj = self._match_valid_url(url)
        series = string.capwords(urllib.parse.unquote(mobj.group('series')).replace('-', ' '))
        episode = mobj.group('episode').zfill(2)
        title = f'{series} {episode}'

        self.debug('SERIES', series)
        self.debug('TITLE', title)

        description = self._og_search_description(webpage)
        self.debug('DESCRIPTION', description)

        servers_ul = get_element_by_class('links-server', webpage)
        servers_li = get_elements_html_by_class('server', servers_ul)
        server_links = [extract_attributes(li)['data-url'] for li in servers_li]

        self.debug('SERVER LINKS', server_links)

        result_url, iframe_url = self._try_server_links(server_links, video_id, url)

        self.debug('RESULT URL', result_url)

        if '.mp4' in result_url:
            result = {
                'url': result_url,
                'http_headers': {'Referer': iframe_url},
            }
        elif '.m3u8' in result_url:
            m3u8_formats = self._extract_m3u8_formats(result_url, video_id, headers={'Referer': iframe_url})
            m3u8_formats_with_referer = [
                {**format_dict, 'http_headers': {'Referer': iframe_url}}
                for format_dict in m3u8_formats
            ]
            self.debug('m3u8 formats', m3u8_formats_with_referer)
            result = {'formats': m3u8_formats_with_referer}
        else:
            raise ExtractorError(f'Weird result url: {result_url}', video_id=video_id)

        return {
            'id': video_id,
            'title': title,
            'series': series,
            'description': description,
            **result,
        }


class AradramaEpisodeListIE(AradramaBaseIE):
    _VALID_URL = _EPISODE_LIST_URL_RE

    def _real_extract(self, url):
        video_id = urllib.parse.unquote(self._match_id(url))
        webpage = self._download_webpage(url, video_id)

        self.debug('INITIAL WEB PAGE', webpage)

        title_htmls = get_elements_by_class('post-title', webpage)

        episode_urls = [
            re.search(r'href=([\'"])(?P<url>.*?)\1', title_html).group('url')
            for title_html in title_htmls
        ]

        self.debug('EPISODE COUNT', len(episode_urls))
        self.debug('EPIOSDE URLS', episode_urls)

        return self.playlist_result(
            entries=[self.url_result(url, ie=AradramaEpisodeIE) for url in episode_urls],
        )


class AradramaSerieIE(AradramaBaseIE):
    _VALID_URL = _SERIES_URL_RE

    def _real_extract(self, url):
        video_id = urllib.parse.unquote(self._match_id(url))
        webpage = self._download_webpage(url, video_id)

        self.debug('INITIAL WEB PAGE', webpage)

        episode_list_url = re.search(rf'href=([\'"])(?P<url>{_EPISODE_LIST_URL_RE}/?)\1', webpage).group('url')

        self.debug('EPISODE LIST URL', episode_list_url)

        return self.url_result(episode_list_url, ie=AradramaEpisodeListIE)


# TODO: Add support for Movie pages too. It should be straightforward since
#       most of the complexity is implemented already.
