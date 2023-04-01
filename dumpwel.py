
import argparse
from datetime import date, time, datetime, timedelta
import getpass
# import gettext
import json
import logging
import os
import os.path as p
import pathlib
import pickle
import re
import requests
from bs4 import BeautifulSoup
import sys
import textwrap
from time import sleep
import urllib
import unicodedata

log = logging.getLogger("dumpwel")

_THISDIR = p.dirname(__file__)

_DATA = p.expanduser("~/Desktop/dumpwel")
_DUMPDIR = p.join(_DATA, "dump")
_DEFAULT_OUTPUTDIR = p.join(_DATA, "output")

_TOP_URL = 'https://photo.wel-kids.jp/'


class Dumpwel(object):
    def __init__(self):
        self.session = requests.Session()
        self.appdatadir = get_appdatadir() / "dumpwel"
        self.cookiefile = p.join(self.appdatadir, "cookie.dat")
        self.config = p.join(self.appdatadir, "config.json")

    def mkAppDir(self):
        if not p.isdir(self.appdatadir):
            os.mkdir(self.appdatadir)

    def saveCookie(self):
        self.mkAppDir()
        with open(self.cookiefile, 'wb') as f:
            pickle.dump(self.session.cookies, f)

    def loadCookie(self):
        if p.isfile(self.cookiefile):
            with open(self.cookiefile, 'rb') as f:
                self.session.cookies.update(pickle.load(f))

    def loadConf(self):
        if p.isfile(self.config):
            with open(self.config, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    return {}
            return data
        return {}

    def saveConf(self, data):
        self.mkAppDir()
        with open(self.config, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=True)
        return data

    def testLogin(self):
        self.loadCookie()
        res = self.session.get(_TOP_URL + "/top/menu", allow_redirects=False)
        if res.status_code == 200:
            return True

    def getCsrfId(self):
        res = self.session.get(_TOP_URL, allow_redirects=False)
        return res.cookies.get("photo_csrf_cookie_name")

    def login(self, useSavedId=True):
        """ ログイン処理
        Args:
            useSavedId (bool, optional): _description_. Defaults to True.

        Returns:
            _type_: _description_
        """

        csrf_id = self.getCsrfId()
        log.info("not logged in.")
        conf = self.loadConf()
        if useSavedId and "id" in conf and conf["id"]:
            id = conf["id"]
        else:
            id = input("login: ")
            conf["id"] = id
            self.saveConf(conf)
        pw = getpass.getpass("password: ")
        loginPayload = {"csrf_test_name": csrf_id, "user_id": id, "user_password": pw, 'keep_login': 1}
        url = 'https://photo.wel-kids.jp/top/login'
        res = self.session.post(url, data=loginPayload)
        if res.status_code == 200:
            self.saveCookie()
        return res

    def iter_album(self):
        """
        https://photo.wel-kids.jp/album/show_list
        https://photo.wel-kids.jp/album/show_list/normal?page=4
        """
        url_fmt = "https://photo.wel-kids.jp/album/show_list?page=%d"
        for page in range(1, 100):
            url = url_fmt % page
            res = self.session.get(url)
            soup = BeautifulSoup(res.text, "html.parser")
            for album in soup.find_all("a", class_="albumLink"):
                albumtitleline = album.find("span", class_="albumtitleline")
                albumtitle = albumtitleline.text.strip()
                datestr = album.find("dd", class_="albumShotTime").text.strip()
                data = dict(title=albumtitle,
                            url=album["href"],
                            datestr=datestr)
                yield data
            if soup.find("li", class_="cPageNextOff"):
                break

    def iter_photo(self, album_data):
        """
        <a class="photo-view" data-url="https://photo.wel-kids.jp/album/photo_viewer/58563119">
                            <img width="320" height="224" src="https://img001-cf.wel-kids.jp/s/0000/0724/2023/02/06/001/526f43535762356d4c555767514e774136637a755a413d3d/320_w.jpg?Expires=1680253200&amp;Signature=Nq5RGDS-dUtxLulPJxdLkN0oqJyUlz942FEPM3K6rATaB0vSnEJfqV~MFT2Wpssb6Jd-jSB~IYlk9Y8o11J8K4tPsJ5eCP7yZ3d-X5unnl75xqU5ARiHanIU2kEzWFDTZ676KeSuOQ8Kvi-kBCI320ymvAc5oerNmKezQV3O2KB~FXD6PwXV3-huxsdE0d5VGIfx633LFa4PMcTkBKZxDN~~RyuDgoz7wQIGuOrGWNd5e1fBtZ1A8OWFJRalNT~-u1metlwe7T7KVuzt0g48rgAwNXFY73ceU~Pr8tn7r0yNOaw0HyqnV-352opDu0GNFXFJh6K-e0O6w9bwivOqDA__&amp;Key-Pair-Id=KQB2RQBLCLSTQ" style="width: 318.571px; height: 223px; top: 0px; left: -48px;">
                        </a>
            <a class="move-page" data-url="https://photo.wel-kids.jp/album/photo/370102/3" onclick="__gaTracker('send', 'event', 'album-pagenation', 'bottom-button', 'next');">&gt;</a>
        """
        for page in range(1, 100):
            url = album_data["url"] + "/%d" % page
            print(url)

            res = self.session.get(url)
            soup = BeautifulSoup(res.text, "html.parser")
            for photo in soup.find_all("a", class_="photo-view"):
                yield photo["data-url"]

            found = False
            for allow in soup.find_all("li", class_="arrow")[1::2]:
                move_page = allow.find("a", class_="move-page")
                next_url = album_data["url"] + "/%d" % (page + 1)
                if move_page and move_page["data-url"] == next_url:
                    found = True
            if found is False:
                break

    def get_photo(self, photo):
        res = self.session.get(photo)
        soup = BeautifulSoup(res.text, "html.parser")
        img = soup.find("img", id="image-main")
        img_url = img["src"]
        res = self.session.get(img_url)
        bin = res.content
        return bin


def get_appdatadir() -> pathlib.Path:
    """
    Returns a parent directory path
    where persistent application data can be stored.

    # linux: ~/.local/share
    # macOS: ~/Library/Application Support
    # windows: C:/Users/<USER>/AppData/Roaming
    """

    home = pathlib.Path.home()

    if sys.platform == "win32":
        return home / "AppData/Roaming"
    elif sys.platform == "linux":
        return home / ".local/share"
    elif sys.platform == "darwin":
        return home / "Library/Application Support"


def sanitize_filename(filename):
    # ファイル名として使えない文字を置換する
    invalid_chars = '<>:"/\\|?*\n'
    replace_chars = '＜＞：”／＼｜？＊_'
    table = str.maketrans(invalid_chars, replace_chars)
    return filename.translate(table)


def main():
    d = Dumpwel()
    log.info("login")
    if not d.testLogin():
        for i in range(3):
            res = d.login(useSavedId=(i == 0))
            if res.status_code == 200:
                break
    for album_data in d.iter_album():
        print(album_data["datestr"], album_data["title"])
        count = 0
        for photo in d.iter_photo(album_data):
            count += 1
            old_folder = p.join(_DUMPDIR, album_data["title"])
            title = sanitize_filename(album_data["title"])
            datestr = album_data["datestr"].replace("/", "-")
            folder = p.join(_DUMPDIR, "%s_%s" % (datestr, title))
            id = photo.split("/")[-1]
            old_fn = p.join(old_folder, "%s.jpg" % id)
            fn = p.join(folder, "%s.jpg" % id)
            fn2 = p.join(folder, "%04d_%s.jpg" % (count, id))
            if not p.isdir(folder):
                os.makedirs(folder)
            if p.isfile(old_fn):
                os.rename(old_fn, fn2)
            elif p.isfile(fn):
                os.rename(fn, fn2)
            elif p.isfile(fn2):
                pass
            else:
                bin = d.get_photo(photo)
                with open(fn2, 'wb') as f:
                    f.write(bin)
        print(count)


if __name__ == "__main__":
    main()
