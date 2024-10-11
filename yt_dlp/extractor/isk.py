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
    get_element_by_id,
    get_element_html_by_class,
    get_element_html_by_id,
    get_element_text_and_html_by_tag,
    urlencode_postdata,
)

_HOSTS = '|'.join([
    # 'eceeq',
    '3isk',
    # '3ick',
    # 'esheaq',
])
_DOMAIN_RE = rf'https?://(?:\w{{1,4}}\.)?(?:{_HOSTS})\.(?:\w{{2,4}})'

_SERIE_ID_RE = r'serie-(?P<series>[\w-]+)'
_EPISODE_ID_RE = r'serie-(?P<series>[\w-]+?)-season-(?P<season>\d+)-episode-(?P<episode>\d+)'

_SERIE_URL_RE = rf'{_DOMAIN_RE}/watch/tvshows/(?P<id>{_SERIE_ID_RE})'
_EPISODE_URL_RE = rf'{_DOMAIN_RE}/watch/episodes/(?P<id>{_EPISODE_ID_RE})'
_SEE_URL_RE = rf'{_EPISODE_URL_RE}/see/?'

_EXTERNAL_URL_RE = _DOMAIN_RE + r'/external\.php'
_3ISK_URL_RE = _DOMAIN_RE + r'/3isk\d+\.php'

_MAIN_IFRAME_URL_RE = _DOMAIN_RE + r'/embed/.+'
# miravd.com
# mwdy.cc
_EMBEDDED_IFRAME_URL_RE = r'https?://[^/]+/embed-[\w-]+\.html'


class IskBaseIE(InfoExtractor):
    def _get_series_name(self, url):
        series = self._match_valid_url(url).group('series')
        series = re.sub(r'-(hd|bt)$', '', series)
        series = re.sub(r'-\d{1,2}[a-zA-Z]{2,3}$', '', series)
        return string.capwords(series.replace('-', ' '))

    def _download_with_referer(self, url, video_id, note, referer, data=None):
        return self._download_webpage(
            url,
            video_id,
            note,
            headers={'Referer': referer},
            data=data,
        )

    def _find_m3u8_url(self, video_id, url, html):
        next_url = url
        next_page = html
        while True:
            if re.match(_EXTERNAL_URL_RE, next_url):
                next_url, next_page = self._handle_external_page(video_id, next_url, next_page)
            elif re.match(_3ISK_URL_RE, next_url):
                if self._is_waiting_page(next_page):
                    next_url, next_page = self._handle_waiting_page(video_id, next_url, next_page)
                elif self._is_watch_page(next_page):
                    return self._handle_watch_page(video_id, next_url, next_page)
                else:
                    raise ExtractorError('Encountered a page with unsupported content')
            elif re.fullmatch(_SEE_URL_RE, next_url):
                return self._handle_watch_page(video_id, next_url, next_page)

    def _handle_external_page(self, video_id, url, html):
        no_script, _ = get_element_text_and_html_by_tag('noscript', html)
        meta_refresh_content = self._html_search_meta('refresh', no_script)
        mobj = re.search(r'url=(?P<url>.+)', meta_refresh_content, re.IGNORECASE)
        next_url = mobj.group('url')

        self.debug('[EXTERNAL] next url', next_url)

        next_page = self._download_with_referer(
            next_url,
            video_id,
            'Downloading waiting url',
            url,
        )

        self.debug('[EXTERNAL] next page', next_page)

        return next_url, next_page

    def _is_waiting_page(self, html):
        return re.search(r'id=[\'"]myForm[\'"]', html) \
            and re.search(r'id=[\'"]inputVal[\'"]', html) \
            and re.search(r'id=[\'"]dinputVal[\'"]', html) \
            and re.search(r'id=[\'"]myLink[\'"]', html) \
            and re.search(r'var(\s+)myUrl(\s*)=', html) \
            and re.search(r'var(\s+)mydUrl(\s*)=', html) \
            and re.search(r'myInput.value(\s*)=(\s*)[\'"].*?[\'"]', html)

    def _is_watch_page(self, html):
        return re.search(r'<iframe (.*)src=[\'"]' + _MAIN_IFRAME_URL_RE + r'[\'"]', html)

    def _handle_waiting_page(self, video_id, url, html):
        next_url, fields = self._extract_form_url_and_fields_js(html)

        self.debug('[WAITING] form url & fields', f'{next_url}\n{fields}')

        next_page = self._download_with_referer(
            next_url,
            video_id,
            'Downloading the url found in the waiting page',
            url,
            data=urlencode_postdata(fields),
        )

        self.debug('[WAITING] next page', next_page)

        return next_url, next_page

    def _handle_watch_page(self, video_id, url, html):
        # The watch page has an iframe (let's call it MAIN) that loads another
        # iframe inside of it (let's call this one EMBEDDED)

        _, main_iframe = get_element_text_and_html_by_tag('iframe', html)
        main_iframe_src = extract_attributes(main_iframe)['src']

        if not re.fullmatch(_MAIN_IFRAME_URL_RE, main_iframe_src):
            raise ExtractorError(f'Expected a url for the main iframe, but got: {main_iframe_src}')

        self.debug('[WATCH] main iframe src', main_iframe_src)

        main_iframe_page = self._download_with_referer(
            main_iframe_src,
            video_id,
            'Downloading main iframe on the watch page',
            url,
        )

        self.debug('[WATCH] main iframe page', main_iframe_page)

        _, embedded_iframe = get_element_text_and_html_by_tag('iframe', main_iframe_page)
        embedded_iframe_src = extract_attributes(embedded_iframe)['src']

        if not re.fullmatch(_EMBEDDED_IFRAME_URL_RE, embedded_iframe_src):
            raise ExtractorError(f'Expected a url for the embedded iframe, but got: {embedded_iframe_src}')

        self.debug('[WATCH] embedded iframe src', embedded_iframe_src)

        embedded_iframe_html = self._download_with_referer(
            embedded_iframe_src,
            video_id,
            'Downloading embedded iframe on the watch page',
            main_iframe_src,
        )

        self.debug('[WATCH] embedded iframe page', embedded_iframe_html)

        return self._reconstruct_m3u8_url(embedded_iframe_html)

    def _reconstruct_m3u8_url(self, html):
        # Example input:
        # ||||||||||function|player|||svg|jwplayer|if|||var|589|||icon|jw|div|on|tracks|cookieData|rewind|tt||seek||path|||||||769|240||60009||adb|hide|org|log|console|resumeAt|vvplay|position|vvad|mwdy|https|insertAfter|detach|ff00|button|getPosition|sec|974|887|013|96|867|178|false|focusable|viewBox|class||2000|w3|||www||http|xmlns|addButton|ff11||06475|23525|29374|97928|30317|31579|29683|38421|30626|72072|H|track_name|length|videoDur|parseInt|split|resume441dy5by6lz6|cookie||data|441dy5by6lz6|video_ad|doPlay||prevt||true|100|club|spe|Rewind|778Z|214|2A4|3H209|3v19|9c4|7l41|9a6|3c0|1v19|4H79|3h48|8H146||3a4|2v125|130|1Zm162|4v62|13a4|51l|7v|278Zm|95|278|1S103|1s6|3Zm|078a21||131|||M113||||Forward|69999|88605|21053|03598|02543|99999|72863|77056|04577|422413|163|210431|860275|03972|689569|893957|124979|52502|174985|57502|04363|13843|480087|93574|99396|160|76396||164107|63589|03604|125|778||993957|rewind2|ready|setCurrentAudioTrack|name|for|getAudioTracks|set_audio_track|xxx|html|fviews|referer|embed|3f11646aaf197a4b7860a8443a385951|1728607790|113|99|79464|hash|file_code|view|op|dl|get|adbon|window|return|over_player_msg|pause|show||complete|play|slow|fadeIn|video_ad_fadein|600|expires|getDuration|floor|Math|time|cache|no|Cache|Content|headers|ajaxSetup|lastt|v2done|tott|vastdone2|vastdone1|cast|aboutlink|abouttext|displaytitle|title|Normal||472|qualityLabels|androidhls|auto|preload|8779|duration||exactfit|stretching||height|width|jpg|00015|01|image|m3u8|master|urlset|unclsk7ylcrt55h3jyzrtfv2p4sbj63axfmw6mkqtzmh35edwcglmbqmkpua|hls|file|sources|setup||vplayer

        # Example output:
        # https://spe.mwdy.club/hls/,unclsk7ylcrt55h3jyzrtfv2p4sbj63axfmw6mkqtzmh35edwcglmbqmkpua,.urlset/master.m3u8

        # To find the domain, we look at the thumbnail used for the player. The
        # video is served from the same domain.
        vplayer_div = get_element_by_id('vplayer', html)
        img_src = self._by_tag_attribute('img', 'src', vplayer_div)
        cdn_domain = urllib.parse.urlparse(img_src).netloc

        path_parts_re = r'''(?x)
        \|(?P<ext>m3u8)
        .*?
        \|(?P<channel>master)
        .*?
        \|(?P<operation>urlset)
        \|(?P<token>\w+)
        .*?
        \|(?P<encoding>hls)
        \|
        '''
        ext, channel, operation, token, encoding = re.search(path_parts_re, html).groups()
        path = f'{encoding}/,{token},.{operation}/{channel}.{ext}'

        return f'https://{cdn_domain}/{path}'

    def _extract_form_url_and_fields_js(self, html):
        form = get_element_by_id('myForm', html)

        url = self._js_rhs(r'myUrl', html)
        fields = {
            self._field_name('inputVal', form):
                self._js_rhs(r'myInput\.value', html),

            self._field_name('dinputVal', form):
                self._js_rhs(r'mydUrl', html),

            self._field_name('myLink', form):
                self._field_value('myLink', form),
        }

        return url, fields

    def _field_name(self, dom_id, html):
        return self._by_id_attribute(dom_id, 'name', html)

    def _field_value(self, dom_id, html):
        return self._by_id_attribute(dom_id, 'value', html)

    def _by_id_attribute(self, dom_id, attribute, html):
        mobj = re.search(rf'id=([\'"]){dom_id}\1[^>]*?{attribute}=([\'"])(?P<attribute>[^\'"]*)\2', html)
        return mobj.group('attribute')

    def _by_tag_attribute(self, tag, attribute, html):
        mobj = re.search(rf'<{tag} [^>]*?{attribute}=([\'"])(?P<attribute>[^\'"]*)\1', html)
        return mobj.group('attribute')

    def _js_rhs(self, lhs, html):
        mobj = re.search(lhs + r'\s*=\s*([\'"])(?P<rhs>.*?)\1', html)
        return mobj.group('rhs')

    def _extract_form_url_and_fields(self, html):
        container = get_element_by_class('single_buttons', html)
        _, form = get_element_text_and_html_by_tag('form', container)

        form_action = self._by_tag_attribute('form', 'action', form)

        if not re.match(_3ISK_URL_RE, form_action):
            raise ExtractorError(f'Expected to find the right <form> but found: {form}')

        fields = {}
        for child in re.finditer(r'<(?:input|button) (?P<attrs>.*?)>', form):
            input_attrs = child.group('attrs')
            name_mobj = re.search(r'name=([\'"])(?P<name>\w+)\1', input_attrs)
            if name_mobj is None:
                continue
            name = name_mobj.group('name')

            value_mobj = re.search(r'value=([\'"])(?P<value>[^\'"]*)\1', input_attrs)
            value = '' if value_mobj is None else value_mobj.group('value')

            fields[name] = value

        return form_action, fields

    def debug(self, name, info):
        self.write_debug('\n')
        self.write_debug('=' * 20)
        self.write_debug('\n')
        self.write_debug(f'{name}:\n')
        self.write_debug(info)
        self.write_debug('\n')


class IskEpisodeIE(IskBaseIE):
    _VALID_URL = _EPISODE_URL_RE

    _TESTS = [{
        'url': 'https://3isk.biz/watch/episodes/serie-leyla-season-1-episode-5/',
        'info_dict': {
            # For videos, only the 'id' and 'ext' fields are required to RUN the test:
            'id': 'serie-leyla-season-1-episode-5',
            'title': 'مسلسل ليلى الحلقة 5',
            'series': 'Leyla Hd',
            'description': 'md5:4b0582caf8331ba46546dfa8c1d5bfb8',
            'ext': 'mp4',
        },
    }, {
        'url': 'https://3isk.biz/watch/episodes/serie-bir-gece-masali-season-1-episode-6/',
        'info_dict': {
            'id': 'serie-bir-gece-masali-season-1-episode-6',
            'title': 'مسلسل حكاية ليلة الحلقة 6',
            'series': 'Leyla Hd',
            'description': 'md5:7824f3d896a0d694376d1d5b5bde41f5',
            'ext': 'mp4',
        },
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        self.debug('INITIAL WEB PAGE', webpage)

        series = self._get_series_name(url)

        mobj = self._match_valid_url(url)
        season_num = mobj.group('season').zfill(2)
        episode_num = mobj.group('episode').zfill(2)

        title = f'{series} {season_num}x{episode_num}'

        description = self._og_search_description(webpage)

        watch_button = get_element_html_by_id('single_watch_btn', webpage) or get_element_html_by_class('single-watch-btn', webpage)
        self.debug('[EPISODE] watch button', watch_button)

        if watch_button.startswith('<a '):
            next_url = extract_attributes(watch_button)['href']
            next_page = self._download_with_referer(
                next_url,
                video_id,
                'Downloading the url found in the Episode page',
                url,
            )
        elif watch_button.startswith('<button '):
            next_url, fields = self._extract_form_url_and_fields(webpage)
            self.debug('[EPISODE] form url & fields', f'{next_url}\n{fields}')
            next_page = self._download_with_referer(
                next_url,
                video_id,
                'Submitting the form found in the Episode page',
                url,
                data=urlencode_postdata(fields),
            )
        else:
            raise ExtractorError(f'Unsupported link element found: {watch_button}')

        self.debug('[EPISODE] next url', next_url)
        self.debug('[EPISODE] next page', next_page)

        m3u8_url = self._find_m3u8_url(video_id, next_url, next_page)

        self.debug('m3u8 url', m3u8_url)

        m3u8_formats = self._extract_m3u8_formats(m3u8_url, video_id)

        self.debug('m3u8 formats', m3u8_formats)

        return {
            'id': video_id,
            'title': title,
            'series': series,
            'description': description,
            'formats': m3u8_formats,
        }


class IskSerieIE(IskBaseIE):
    _VALID_URL = _SERIE_URL_RE

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id)

        self.debug('INITIAL WEB PAGE', webpage)

        episodes_container = get_element_by_id('episodes', webpage)

        episode_urls = [
            mobj.group('url') for mobj in re.finditer(r'href=([\'"])(?P<url>.*?)\1', episodes_container)
        ]

        self.debug('EPISODE COUNT', len(episode_urls))
        self.debug('EPIOSDE URLS', episode_urls)

        return self.playlist_result(
            entries=[self.url_result(url, ie=IskEpisodeIE) for url in episode_urls],
        )


# TODO: Add support for Movie pages too. It should be straightforward since
#       most of the complexity is implemented already.
