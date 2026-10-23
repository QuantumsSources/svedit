import os
import yaml
import pickle
import svedit_core as core

from typing import Any
from urllib import request
from urllib.error import URLError
from yaml.scanner import ScannerError

class InvalidDownloadError(Exception):
    pass

class IncompleteUpdateError(Exception):
    pass

class NoInternetError(Exception):
    pass

def dl_db(custom_url: str|None = None):
    url = custom_url if custom_url is not None else core.DATABASE_URL
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with request.urlopen(req) as r, open(core.YAML_PATH, "wb") as out:
        out.write(r.read())

class DSDatabaseEntry:
    def __init__(self, e: dict[str, Any]):
        self.name: str = e.get("name", "?????")
        self.localized_name: str = e.get("localizedName", self.name)
        self.save_name: str = e.get("saveName", self.name)

        _metadata: dict = e.get("metadata", { })
        self.publisher: str = _metadata.get("publisher", "???")
        self.developer: str = _metadata.get("developer", "???")
        self.release_date: str = _metadata.get("releaseDate", "????-??-??")
        self.genres: list[str] = str(_metadata.get("genre")).split(" / ")
        self.languages: list[str] = _metadata.get("languages", [])

def get_db(force_redownload: Any = None, custom_url: str|None = None) -> dict[str, Any]:
    def _clean():
        if core.PKL_PATH.exists():
            os.remove(core.PKL_PATH)
        if core.YAML_PATH.exists():
            os.remove(core.YAML_PATH)

    try:
        if force_redownload or custom_url is not None:
            dl_db(custom_url)
        else:
            if core.PKL_PATH.exists() and core.PKL_PATH.stat().st_mtime >= core.PKL_PATH.stat().st_mtime:
                with open(core.PKL_PATH, "rb") as f:
                    data = pickle.load(f)
                return data
            if not core.YAML_PATH.exists():
                dl_db(custom_url)

        with open(core.YAML_PATH, "r") as f:
            try:
                data = yaml.load(f, Loader=yaml.CSafeLoader)
            except ScannerError as e:
                raise InvalidDownloadError(e)
        with open(core.PKL_PATH, "wb") as w:
            pickle.dump(data, w)

        return data
    except URLError:
        _clean()
        raise NoInternetError("Check your internet connection and try again!")
    except KeyboardInterrupt:
        _clean()
        raise IncompleteUpdateError

def get_db_entry(db: dict[Any, Any]|None, product: str|None) -> DSDatabaseEntry:
    if db is None or product is None:
        return DSDatabaseEntry({ })
    return DSDatabaseEntry(db.get(product, { }))