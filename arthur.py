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
import os
from os.path import join
import glob
import shutil
import tarfile
import re
from itertools import chain
import subprocess
import tempfile

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
        self.path = opts.get('path')

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

    def install(self):
        if os.path.exists(self.term):
            # process this local file
            pkgbuild = self.extract_PKGBUILD(self.term)
            pacman, aur = self.find_dependencies(pkgbuild)
            import ipdb; ipdb.set_trace();
        else:
            # dl the archive
            pass
        sys.exit(1)

    def download(self, pkg=None):
        pkg = pkg if pkg is not None else self.term
        url = self.url('info', pkg)
        response = self.decode(url)
        if response['type'] == 'error':
            sys.exit('%s: %s' % (pkg, response['results']))
        pkg = response['results']
        download_url = self.aur(pkg['URLPath'])
        pkgpath = urlparse.urlparse(download_url).path
        file_name = os.path.basename(pkgpath)

        response = urllib2.urlopen(download_url)
        download = open(file_name, 'wb')
        shutil.copyfileobj(response.fp, download)
        download.close()
        pkgbuild = self.extract_PKGBUILD(file_name)
        pacman, aur = self.find_dependencies(pkgbuild)
        for dep in aur:
            Arthur(term=[dep]).download()

        # dump the pkgbuild to a temp file
        t = tempfile.NamedTemporaryFile()
        t.write(pkgbuild)
        t.seek(0)

        # now we edit that file
        t = self.edit_PKGBUILD(t)
        print t.read()

        # overwrite the real pkgbuild withthe contents of t
        # run makepkg -s


    def edit_PKGBUILD(self, fp):
        editor = os.getenv('EDITOR', 'vim')
        subprocess.call('%s %s' % (editor, fp.name), shell=True)
        return fp

    def extract_PKGBUILD(self, file_name):
        file = tarfile.open(file_name)
        file.extractall()
        return open(join(file_name.replace('.tar.gz', ''),
                    'PKGBUILD')).read()

    def find_dependencies(self, pkgbuild):
        pacman = []
        aur = []
        # for dep in self.find_dependencies(pkgbuild):
        #     if self.in_sync(dep):
        #         pacman.append(dep)
        #     else:
        #         aur.append(dep)
        # print pacman, aur

        depends = re.findall('[^opt](?:make)?depends=\((.*?)\)', pkgbuild, re.S)
        depends = chain(*[de.split() for de in depends])
        depends = (de.strip("'") for de in depends if de != '\\')
        for dep in depends:
            match = re.match('(.[^=><]*)', dep).group()
            if self.in_sync(match):
                pacman.append(match)
            else:
                aur.append(match)
        return pacman, aur

    def in_sync(self, pkg):
        for repo in ['core', 'community', 'extra']:
            path = join('/var/lib/pacman/sync', repo)
            if glob.glob(join(path, pkg+'-*')):
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

def install(*args, **opts):
    """install PACKAGE from the AUR"""
    if args:
        Arthur(term=args, **opts).install()
    else:
        usage = __file__ + ' install ' + install_usage
        help_cmd(install, usage, install_options)

install_options = [
    ('v', 'verbose', False, 'verbose output'),
    ('d', 'debug', False, 'do not actually query aur'),
    ('p', 'path', False, 'path to pkgbuil archive'),
]
install_usage = '[options] PACKAGE'


cmds = {
    '^search': (search, search_options, search_usage),
    '^install': (install, install_options, install_usage)
}

if __name__ == "__main__":
    dispatch(cmdtable=cmds)
