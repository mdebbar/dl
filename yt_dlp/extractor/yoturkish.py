import re

from .common import InfoExtractor
from ..utils import (
    get_element_by_id,
    js_to_json,
)


class YoTurkishEpisodeIE(InfoExtractor):
    # _VALID_URL = r'''(?x)
    #   https?://
    #   (?:www1?\.)?yoturkish\.com/
    #   (?P<id>.+?)
    #   /
    #   '''
    _VALID_URL = r'''(?x)
      https?://
      (?:www1?\.)?yoturkish\.com/
      (?P<id>[0-9A-Za-z_-]+?-episode-\d+)
      '''
    _TESTS = [{
        'url': 'https://www1.yoturkish.com/leyla-episode-4/',
        'info_dict': {
            # For videos, only the 'id' and 'ext' fields are required to RUN the test:
            'id': 'leyla-episode-4',
            'ext': 'mp4',
            # Then if the test run fails, it will output the missing/incorrect fields.
            # Properties can be added as:
            # * A value, e.g.
            #     'title': 'Video title goes here',
            # * MD5 checksum; start the string with 'md5:', e.g.
            #     'description': 'md5:098f6bcd4621d373cade4e832627b4f6',
            # * A regular expression; start the string with 're:', e.g.
            #     'thumbnail': r're:^https?://.*\.jpg$',
            # * A count of elements in a list; start the string with 'count:', e.g.
            #     'tags': 'count:10',
            # * Any Python type, e.g.
            #     'view_count': int,
        },
    }, {
        'url': 'https://yoturkish.com/bir-gece-masali-episode-1/',
        'info_dict': {
            'id': 'bir-gece-masali-episode-1',
            'ext': 'mp4',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        title = self._html_search_regex(r'<h1[^>]*>(.+?)</h1>', webpage, 'title')
        description = self._og_search_description(webpage)

        # This website hides the <iframe> elements inside JavaScript code.
        #
        # On startup, it attaches click listeners to the "Option [n]" buttons.
        # It inserts a different <iframe> element based on which button was
        # clicked.

        player_div = get_element_by_id('player', webpage)
        iframe_srcs = filter(
            lambda url: YoTurkishVideoIE.suitable(url),
            re.findall(r'<iframe [^>]*src=[\'"](.*?)[\'"]', player_div),
        )
        one_iframe_src = next(iframe_srcs)

        # print('\n')
        # print('URL:', one_iframe_src)
        # # print('URLS: \n-', '\n- '.join(iframe_srcs))
        # print('\n')

        # return self.playlist_result(
        #     [self.url_result(url, url_transparent=True, ie=YoTurkishVideoIE.ie_key()) for url in iframe_srcs],
        #     multi_video=True,
        #     playlist_id=video_id,
        #     playlist_title=title,
        #     playlist_description=description,
        # )

        return self.url_result(
            one_iframe_src,
            url_transparent=True,
            ie=YoTurkishVideoIE.ie_key(),
            video_id=video_id,
            video_title=title,
            video_description=description,
        )


class YoTurkishVideoIE(InfoExtractor):
    _VALID_URL = [
        # r'https?://rufiiguta.com/\?v=(?P<id>[0-9A-Za-z_-]+)',
        r'https?://kitraskimisi.com/e/(?P<id>[0-9A-Za-z_-]+)',
    ]

    def _real_extract(self, url):
        # print('== YoTurkishVideoIE ==')
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        video_data = self._find_jwplayer_data(webpage, video_id, transform_source=js_to_json)
        if (video_data is None):
            video_data = self._extract_jwplayer_data(webpage, video_id, require_title=False, transform_source=js_to_json)
        # print('VIDEO DATA:', video_data)
        return video_data
