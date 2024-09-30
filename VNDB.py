#!/opt/homebrew/bin/python3
import socket
import json
import time
import re
import easy_logging


logger = easy_logging.get_logger('VNDB')

DATE_FMT = r'%y%m%d'
TITLE_FMT = '[{releases[0][producers][0][represent]}] [{released_date}] {original}'


PROD_DICT = {
    '平安亭': ['Heiantei'],
    'Lilith': [lambda s: re.match(r'(\S+\s)*Lilith', s)],
    'ANIM': ['Anim'],
    'Kaguya': [lambda s: re.match(r'(\S+\s)*Kaguya(\s\S+)*', s)],
    'ALICESOFT': ['Alice Soft']
}


class vndbException(Exception):
    pass


class NotFoundError(vndbException):
    pass


class VNDB:
    """ Python interface for vndb's api (vndb.org), featuring cache """
    protocol = 1

    def __init__(self, clientname, clientver, username=None, password=None):
        self.sock = socket.socket()

        logger.info('Connecting to api.vndb.org')
        self.sock.connect(('api.vndb.org', 19534))
        logger.info('Connected')

        logger.info('Authenticating')
        if (username is None) or (password is None):
            self.sendCommand('login', {'protocol': self.protocol, 'client': clientname,
                                       'clientver': clientver})
        else:
            self.sendCommand('login', {'protocol': self.protocol, 'client': clientname,
                                       'clientver': clientver, 'username': username, 'password': password})
        res = self.getRawResponse()
        if res.find('error ') == 0:
            raise vndbException(json.loads(' '.join(res.split(' ')[1:]))['msg'])
        logger.info('Authenticated')

        self.cache = {'get': []}
        self.cachetime = 720  # cache stuff for 12 minutes

    def close(self):
        self.sock.close()

    def get(self, type, flags, filters, options):
        """ Gets a VN/producer

        Example:
        >>> results = vndb.get('vn', 'basic', '(title="Clannad")', '')
        >>> results['items'][0]['image']
        u'http://s.vndb.org/cv/99/4599.jpg'
        """
        args = '{0} {1} {2} {3}'.format(type, flags, filters, options)
        for item in self.cache['get']:
            if (item['query'] == args) and (time.time() < (item['time'] + self.cachetime)):
                return item['results']

        self.sendCommand('get', args)
        res = self.getResponse()[1]
        self.cache['get'].append({'time': time.time(), 'query': args, 'results': res})
        return res

    def sendCommand(self, command, args=None):
        """ Sends a command

        Example
        >>> self.sendCommand('test', {'this is an': 'argument'})
        """
        whole = ''
        whole += command.lower()
        if isinstance(args, str):
            whole += ' ' + args
        elif isinstance(args, dict):
            whole += ' ' + json.dumps(args)
        logger.info('⚙️  {}'.format('{0}\x04'.format(whole)))
        self.sock.send(whole.encode('utf8') + b'\x04')

    def getResponse(self):
        """ Returns a tuple of the response to a command that was previously sent

        Example
        >>> self.sendCommand('test')
        >>> self.getResponse()
        ('ok', {'test': 0})
        """
        res = self.getRawResponse()
        cmdname = res.split(' ')[0]
        if len(res.split(' ')) > 1:
            args = json.loads(' '.join(res.split(' ')[1:]))

        if cmdname == 'error':
            if args['id'] == 'throttled':
                raise vndbException('Throttled, limit of 100 commands per 10 minutes')
            else:
                raise vndbException(args['msg'])
        return (cmdname, args)

    def getRawResponse(self):
        """ Returns a raw response to a command that was previously sent

        Example:
        >>> self.sendCommand('test')
        >>> self.getRawResponse()
        'ok {"test": 0}'
        """
        finished = False
        whole = b''
        while not finished:
            whole += self.sock.recv(4096)
            if b'\x04' in whole:
                finished = True
        return whole.replace(b'\x04', b'').strip().decode()


class VNDBClient:
    __CLIENT_NAME__ = 'VNDB String Formatter'
    __CLIENT_VER__ = '0.0.1'

    def __init__(self, username=None, password=None):
        self._instance = VNDB(self.__CLIENT_NAME__, self.__CLIENT_VER__, username=username, password=password)
        self.ret_dict = True
        self.title_fmt = TITLE_FMT
        self.date_fmt = DATE_FMT

    def get(self, filters, type='vn', flags='basic', num=None, options='{"results":25}', ret_dict=None):
        if ret_dict is None:
            ret_dict = self.ret_dict
        more = True

        options_dict: dict = json.loads(options) if options else {"results": 25}
        options_dict.setdefault('page', 1)
        N = 0
        ret = []
        while more:
            options = json.dumps(options_dict)
            d = self._instance.get(type, flags, filters, options)
            options_dict['page'] += 1
            N += d['num'] if ret_dict is False else len(d['items'])
            if ret_dict:
                ret.extend(d['items'])
            else:
                ret.append(d)
            more = d['more']
            if num is not None:
                if N >= num:
                    more = False
                ret = ret[:num]
        logger.info(f'{len(ret)} related entries found!')
        return ret

    def search(self, pattern, type='vn', flags='basic', num=None, options='{"results":25}', ret_dict=None, method=None):
        if method is None:
            method = 'search~'
        assert type in ['vn', 'producer', 'character', 'staff']
        return self.get(f'({method}"{pattern}")', type=type, flags=flags, num=num, options=options, ret_dict=ret_dict)

    def search_vn(self, pattern, flags='basic', num=None, options='{"results":25}', ret_dict=None, method=None):
        return self.search(pattern, type='vn', flags=flags, num=num, options=options, ret_dict=ret_dict, method=method)

    def search_release(self, pattern, flags='basic,producers', num=None, options='{"results":25}', ret_dict=None):
        if isinstance(pattern, int):
            q = f'(vn="{pattern}")'
        else:
            q = f'(title~"{pattern}")'
        ens = self.get(q, type='release', flags=flags, num=num, options=options, ret_dict=ret_dict)
        for en in ens:
            for prod in en['producers']:
                prod_name = prod['name']
                _represent = ""
                for k, v in PROD_DICT.items():
                    for _v in v:
                        if isinstance(_v, str):
                            if _v == prod_name:
                                _represent = k
                                break
                        elif _v(prod_name):
                            _represent = k
                            break
                    if _represent:
                        break
                prod['represent'] = prod_name if not _represent else _represent
        return ens

    def search_characters(self, pattern, flags='basic', num=None, options='', ret_dict=None):
        if not isinstance(pattern, int):
            pattern = self.search_vn(pattern, num=1, ret_dict=True)[0]['id']
        return self.get(f'(vn="{pattern}")', type='character', flags=flags, num=num, options=options, ret_dict=ret_dict)

    def full_search(
        self,
        pattern,
        flags='basic,releases,characters',
        num=None,
        options='{"results":25}',
        release_kwds={},
        character_kwds={},
        method=None
    ):
        flag_list = flags.split(',')
        FIND_RELEASES = False
        FIND_CHARACTERS = False
        if 'releases' in flag_list:
            flag_list.remove('releases')
            FIND_RELEASES = True
        if 'characters' in flag_list:
            flag_list.remove('characters')
            FIND_CHARACTERS = True
        flags = ','.join(flag_list)
        ret = []
        for vn in self.search_vn(pattern, flags, num=num, options=options, ret_dict=True, method=method):
            if FIND_RELEASES:
                vn['releases'] = self.search_release(vn['id'], **release_kwds, ret_dict=True)
                # vn['releases'] = self.search_release(vn['title'], **release_kwds, ret_dict = True)
            if FIND_CHARACTERS:
                vn['characters'] = self.search_characters(vn['id'], **character_kwds, ret_dict=True)
            ret.append(vn)
        return ret

    def titles(self, pattern, method=None, num=None, callback=None):
        ens = self.full_search(pattern, flags='basic,relations,releases', num=num,
                               release_kwds={'num': 25}, method=method)
        if len(ens) < 1:
            raise NotFoundError('No results found.')
        for i, en in enumerate(ens):
            if num is not None:
                if i >= num:
                    break
            if callback is not None:
                callback(en)
            released_date = time.strftime(self.date_fmt, time.strptime(en['released'], '%Y-%m-%d'))
            yield self.title_fmt.format(released_date=released_date, **en)

    def title(self, pattern, method=None):
        return next(self.titles(pattern, method, num=1))

def main():
    import sys
    sys.tracebacklimit = 3
    import argparse
    # construct the argument parse and parse the arguments
    ap = argparse.ArgumentParser(description='VNDB search tool',
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('pattern', help="Search pattern")
    ap.add_argument('--method', default='search~',
                    help='Search method. Possible choices include: \
                        for example, "id=", "title~", "original~", or  "search~" (default)')
    ap.add_argument('--title-fmt', default=TITLE_FMT, help='title format')
    ap.add_argument('--date-fmt', default=DATE_FMT, help='Date format')
    ap.add_argument('--options', '-O', default='{"results":25}', help='search options')
    ap.add_argument('--raw', action='store_true', help='output raw text')
    ap.add_argument('--show-url', action='store_true', help='show the related page on vndb.org')
    ap.add_argument('--num', type=int, default=None, help='Max number of results')
    args = ap.parse_args()

    pattern = args.pattern
    method = args.method
    options = args.options
    raw = args.raw
    show_url = args.show_url
    num = args.num

    c = VNDBClient()

    ids = []
    for title in c.titles(pattern, method=method, num=num, callback=(lambda en: ids.append(en['id']))):
        if raw:
            print(title)
        else:
            print('🔯', title, '🔯', sep='')

        if show_url:
            id = ids[-1]
            print(f'https://vndb.org/v{id}')

if __name__ == '__main__':
    main()
