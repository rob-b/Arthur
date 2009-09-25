#!/usr/bin/env python
from opster import command
from opster import help_cmd
from opster import dispatch
import urllib
import urllib2
import urlparse
import json
import sys
import curses
import os.path
import glob
import shutil
import tarfile
import re
from itertools import chain

class OutputFormatter(object):
    """Style the output of a command"""

    def __init__(self, str=None, color=''):
        import textwrap
        import curses

        self.str = str
        self.wrapper = textwrap.TextWrapper()

        curses.setupterm()
        fg = curses.tigetstr('setaf')
        bg = curses.tigetstr('setab')
        self.cmap = {}
        for color in "BLUE GREEN CYAN RED MAGENTA YELLOW WHITE BLACK".split():
            index = getattr(curses, 'COLOR_%s' % color)
            self.cmap[color] = curses.tparm(fg, index)
            self.cmap['BG_%s' % color] = curses.tparm(bg, index)
        self.cmap['NORMAL'] = curses.tigetstr('sgr0')
        self.cmap['BG_NORMAL'] = curses.tigetstr('sgr0')
        self.cmap['BOLD'] = curses.tigetstr('bold')

    def render(self):
        self.wrapper.initial_indent = self.indent
        self.wrapper.subsequent_indent = self.subsequent_indent
        for line in self.wrapper.wrap(self.str):
            try:
                output = u'%s%s%s%s%s' % (self.cmap[self.bg.upper()],
                                          self.style,
                                          self.cmap[self.fg.upper()],
                                          line,
                                          self.cmap['NORMAL'])
            except (KeyError, AttributeError):
                output = line
            output = output.encode('utf8') + self.separator
            sys.stdout.write(output)

    def __call__(self, str, **kwargs):
        self.str = str
        self.indent = kwargs.get('indent', '')
        self.subsequent_indent = kwargs.get('subsequent_indent', self.indent)
        self.fg = kwargs.get('fg')
        self.bg = kwargs.get('bg')
        self.bg = 'BG_%s' % self.bg if self.bg else 'BG_NORMAL'
        self.separator = kwargs.get('separator', '\n')
        self.style = kwargs.get('style', '')
        try:
            self.style = self.cmap[self.style.upper()]
        except KeyError:
            pass

        self.render()

class Arthur(object):

    search_url = 'http://aur.archlinux.org/rpc.php?type=search&arg='
    rpc_url = 'http://aur.archlinux.org/rpc.php'
    aur_url = 'http://aur.archlinux.org'

    def __init__(self, term=None, formatter=OutputFormatter(), **opts):
        self.term = ' '.join(term) if term else term
        self.segments = list(urlparse.urlsplit(self.rpc_url))
        self.debug = opts.get('debug', False)
        self.formatter = formatter

    def aur(self, path):
        segments = list(urlparse.urlsplit(self.aur_url))
        segments[2] = path
        return urlparse.urlunsplit(segments)

    def url(self, type, arg=None):
        data = {'type': type}
        if arg is not None:
            data['arg'] = arg
        self.segments[3] = urllib.urlencode(data)
        return urlparse.urlunsplit(self.segments)

    def decode(self, url):
        if self.debug:
            return json.load(open('cache.json'))
        try:
            return json.loads(urllib2.urlopen(url).read())
        except URLError, e:
            sys.exit(e.args)

    def search(self):
        if not self.term:
            sys.exit(1)
        url = self.url('search', self.term)
        response = self.decode(url)
        if response['type'] == 'error':
            sys.exit('%s: %s' % (self.term, response['results']))
        packages = sorted(response['results'], key=lambda x: x['Name'])
        for package in packages:
            pkg_detail = "aur/%(Name)s %(Version)s (%(NumVotes)s)" % package
            self.formatter('aur/', fg='magenta', separator='', style='bold')
            self.formatter('%(Name)s ' % package, separator=' ', fg='white',
                           style='bold')
            color = 'red' if int(package['OutOfDate']) else 'green'
            self.formatter('%(Version)s ' % package, separator=' ', fg=color,
                          style='bold')
            self.formatter('(%(NumVotes)s)' % package, fg='black', bg='yellow')
            self.formatter("%(Description)s" % package, indent="\t")

    def download(self):
        url = self.url('info', self.term)
        response = self.decode(url)
        if response['type'] == 'error':
            sys.exit('%s: %s' % (self.term, response['results']))
        pkg = response['results']
        download_url = self.aur(pkg['URLPath'])
        pkgpath = urlparse.urlparse(download_url).path
        file_name = os.path.basename(pkgpath)

        response = urllib2.urlopen(download_url)
        download = open(file_name, 'wb')
        shutil.copyfileobj(response.fp, download)
        download.close()

        for dep in self.parse(file_name):
            print dep

    def parse(self, file_name):
        file = tarfile.open(file_name)
        file.extractall()
        pkgbuild = open(os.path.join(file_name.replace('.tar.gz', ''),
                        'PKGBUILD')).read()
        depends = re.findall('(?:make)?depends=\((.*?)\)', pkgbuild, re.S)
        depends = chain(*[de.split() for de in depends])
        depends = (de.strip("'") for de in depends if de != '\\')
        for dep in depends:
            yield re.match('(.[^=><]*)', dep).group()


    def in_local_db(self, pkg):
        for repo in ['core', 'community', 'extra']:
            path = os.path.join('/var/lib/pacman/sync', repo)
            if glob.glob(os.path.join(path, pkg, '*')):
                return repo
        return False

def search(*args, **opts):
    """Search the AUR for PACKAGE"""
    if args:
        Arthur(term=args, **opts).search()
    else:
        usage = __file__ + ' search ' + search_usage
        help_cmd(search, usage, search_options)

search_options = [
    ('v', 'verbose', False, 'verbose output'),
    ('d', 'debug', False, 'do not actually query aur'),
]
search_usage = '[options] PACKAGE'

def download(*args, **opts):
    """Download PACKAGE from the AUR"""
    if args:
        Arthur(term=args, **opts).download()
    else:
        usage = __file__ + ' download ' + download_usage
        help_cmd(download, usage, download_options)

download_options = [
    ('v', 'verbose', False, 'verbose output'),
    ('d', 'debug', False, 'do not actually query aur'),
]
download_usage = '[options] PACKAGE'


cmds = {
    '^search': (search, search_options, search_usage),
    '^download': (download, download_options, download_usage)
}

if __name__ == "__main__":
    dispatch(cmdtable=cmds)
