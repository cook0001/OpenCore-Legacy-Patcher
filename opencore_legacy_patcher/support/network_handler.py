"""
network_handler.py: Library dedicated to Network Handling tasks including downloading files

Primarily based around the DownloadObject class, which provides a simple
object for libraries to query download progress and status
"""

import time
import requests
import threading
import logging
import enum
import hashlib
import atexit

from typing import Optional, Union
from pathlib import Path
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import utilities


def _create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = _create_session()


class DownloadStatus(enum.Enum):
    """
    Enum for download status
    """

    INACTIVE:    str = "Inactive"
    DOWNLOADING: str = "Downloading"
    ERROR:       str = "Error"
    COMPLETE:    str = "Complete"


class NetworkUtilities:
    """
    Utilities for network related tasks, primarily used for downloading files
    """

    def __init__(self, url: str = None) -> None:
        self.url: str = url

        if self.url is None:
            self.url = "https://github.com"


    def verify_network_connection(self) -> bool:
        """
        Verifies that the network is available

        Returns:
            bool: True if network is available, False otherwise
        """

        try:
            response = SESSION.head(self.url, timeout=5, allow_redirects=True)
            return response.status_code < 500
        except requests.exceptions.RequestException:
            return False

    def validate_link(self) -> bool:
        """
        Check for error

        Returns:
            bool: True if link is valid, False otherwise
        """
        try:
            response = SESSION.head(self.url, timeout=5, allow_redirects=True)
            if response.status_code == 405:
                with SESSION.get(self.url, timeout=5, allow_redirects=True, stream=True) as get_resp:
                    get_resp.raise_for_status()
            else:
                response.raise_for_status()
            return True
        except requests.exceptions.RequestException:
            return False


    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Wrapper for requests's get method
        Implement additional error handling

        Parameters:
            url (str): URL to get
            **kwargs: Additional parameters for requests.get

        Returns:
            requests.Response: Response object from requests.get
        """

        kwargs.setdefault("timeout", (10, 30))
        try:
            return SESSION.get(url, **kwargs)
        except requests.exceptions.RequestException as error:
            logging.warning(f"Error calling requests.get: {error}")
            return requests.Response()

    def post(self, url: str, **kwargs) -> requests.Response:
        """
        Wrapper for requests's post method
        Implement additional error handling

        Parameters:
            url (str): URL to post
            **kwargs: Additional parameters for requests.post

        Returns:
            requests.Response: Response object from requests.post
        """

        kwargs.setdefault("timeout", (10, 30))
        try:
            return SESSION.post(url, **kwargs)
        except requests.exceptions.RequestException as error:
            logging.warning(f"Error calling requests.post: {error}")
            return requests.Response()


class DownloadObject:
    """
    Object for downloading files from the network

    Usage:
        >>> download_object = DownloadObject(url, path)
        >>> download_object.download(display_progress=True)

        >>> if download_object.is_active():
        >>>     print(download_object.get_percent())

        >>> if not download_object.download_complete:
        >>>     print("Download failed")

        >>> print("Download complete"")

    """

    CHUNK_SIZE:     int   = 64 * 1024
    MAX_RETRIES:    int   = 4
    RETRY_BACKOFF:  float = 1.0
    STREAM_TIMEOUT: tuple = (10, 30)

    def __init__(self, url: str, path: str, checksum_algo: Optional["hashlib._Hash"] = None) -> None:
        self.url:       str = url
        self.status:    DownloadStatus = DownloadStatus.INACTIVE
        self.error_msg: str = ""
        self.filename:  str = self._get_filename()

        self.filepath:  Path = Path(path)

        self.total_file_size:      float = 0.0
        self.downloaded_file_size: float = 0.0
        self.start_time:           float = time.time()

        self.error:             bool = False
        self.should_stop:       bool = False
        self.download_complete: bool = False
        self.has_network:       bool = False

        self.active_thread: threading.Thread = None

        self.checksum = None
        self._checksum_algo_name: Optional[str] = getattr(checksum_algo, "name", None) if checksum_algo is not None else None
        self._checksum_storage: Optional["hashlib._Hash"] = checksum_algo

        self._probe_remote()


    def __del__(self) -> None:
        if self.status == DownloadStatus.DOWNLOADING:
            self.stop()


    def download(self, display_progress: bool = False, spawn_thread: bool = True) -> None:
        """
        Download the file

        Spawns a thread to download the file, so that the main thread can continue
        Note sleep is disabled while the download is active

        Parameters:
            display_progress (bool): Display progress in console
            spawn_thread (bool): Spawn a thread to download the file, otherwise download in the current thread

        """
        self.status = DownloadStatus.DOWNLOADING
        logging.info(f"Starting download: {self.filename}")
        if spawn_thread:
            if self.active_thread and self.active_thread.is_alive():
                logging.error("Download already in progress")
                return
            self.active_thread = threading.Thread(target=self._download, args=(display_progress,))
            self.active_thread.start()
            return

        self._download(display_progress)


    def download_simple(self, verify_checksum: bool = False) -> Union[str, bool]:
        """
        Alternative to download(), mimics  utilities.py's old download_file() function

        Parameters:
            verify_checksum (bool): Return checksum of downloaded file if True

        Returns:
            If verify_checksum is True, returns the checksum of the downloaded file
            Otherwise, returns True if download was successful, False otherwise
        """

        if verify_checksum:
            self._checksum_algo_name = "sha256"
            self._checksum_storage = hashlib.sha256()

        self.download(spawn_thread=False)

        if not self.download_complete:
            return False

        return self.checksum if self._checksum_storage else True


    def _get_filename(self) -> str:
        """
        Get the filename from the URL

        Returns:
            str: Filename
        """

        return Path(self.url).name


    def _probe_remote(self) -> None:
        """
        Verify remote reachability and populate expected Content-Length in a single HEAD request
        """

        try:
            result = SESSION.head(self.url, allow_redirects=True, timeout=5)
            self.has_network = result.status_code < 500
            if "Content-Length" in result.headers and result.status_code < 400:
                self.total_file_size = float(result.headers["Content-Length"])
        except requests.exceptions.RequestException as e:
            logging.debug(f"HEAD probe failed for {self.url}: {e}")
            self.has_network = False
            self.total_file_size = 0.0


    def _reset_transfer(self) -> None:
        self.downloaded_file_size = 0.0
        self.start_time = time.time()
        if self._checksum_algo_name:
            self._checksum_storage = hashlib.new(self._checksum_algo_name)
        elif self._checksum_storage is not None:
            self._checksum_storage = None


    def _update_checksum(self, chunk: bytes) -> None:
        """
        Update checksum with new chunk

        Parameters:
            chunk (bytes): Chunk to update checksum with
        """
        if self._checksum_storage:
            self._checksum_storage.update(chunk)


    def _check_free_space(self, required_bytes: float) -> None:
        if required_bytes <= 0:
            return
        available_space = utilities.get_free_space(Path(self.filepath).parent)
        if required_bytes > available_space:
            msg = f"Not enough free space to download {self.filename}, need {utilities.human_fmt(required_bytes)}, have {utilities.human_fmt(available_space)}"
            logging.error(msg)
            raise Exception(msg)


    @staticmethod
    def _parse_content_range(header: Optional[str]) -> Optional[tuple[int, Optional[int]]]:
        """
        Parse RFC 9110 Content-Range header into (start_byte, total_bytes_or_None)
        """
        if not header or not header.lower().startswith("bytes "):
            return None
        spec = header[6:].strip()
        range_part, sep, total_part = spec.partition("/")
        if not sep or "-" not in range_part:
            return None
        start_str, _, end_str = range_part.partition("-")
        if not (start_str.isdigit() and end_str.isdigit()):
            return None
        total = int(total_part) if total_part.isdigit() else None
        return int(start_str), total


    @staticmethod
    def _is_retryable_exception(exc: Exception) -> bool:
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
            return exc.response.status_code in (408, 429) or exc.response.status_code >= 500
        return isinstance(exc, requests.exceptions.RequestException)


    def _sleep_before_retry(self, attempt: int) -> None:
        delay = min(self.RETRY_BACKOFF * (2 ** attempt), 16.0)
        deadline = time.monotonic() + delay
        while not self.should_stop and time.monotonic() < deadline:
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))


    def _prepare_working_directory(self, path: Path) -> bool:
        """
        Validates working enviroment, including free space and removing existing files

        Parameters:
            path (str): Path to the file

        Returns:
            bool: True if successful, False if not
        """

        try:
            if Path(path).exists():
                logging.info(f"Deleting existing file: {path}")
                Path(path).unlink()

            if not Path(path).parent.exists():
                logging.info(f"Creating directory: {Path(path).parent}")
                Path(path).parent.mkdir(parents=True, exist_ok=True)

            self._check_free_space(self.total_file_size)

        except Exception as e:
            self.error = True
            self.error_msg = str(e)
            self.status = DownloadStatus.ERROR
            logging.error(f"Error preparing working directory {path}: {self.error_msg}")
            return False

        logging.info(f"- Directory ready: {path}")
        return True


    def _cleanup_partial_file(self) -> None:
        try:
            if self.filepath.exists():
                self.filepath.unlink()
        except OSError as e:
            logging.warning(f"Failed to remove partial download {self.filepath}: {e}")


    def _download(self, display_progress: bool = False) -> None:
        """
        Download the file with retry and HTTP Range resume support

        Libraries should invoke download() instead of this method

        Parameters:
            display_progress (bool): Display progress in console
        """

        utilities.disable_sleep_while_running()
        atexit.register(self.stop)

        try:
            if self.should_stop:
                raise RuntimeError("Download stopped")

            self.error = False
            self.error_msg = ""
            self.download_complete = False
            self.downloaded_file_size = 0.0
            self.start_time = time.time()

            if self._prepare_working_directory(self.filepath) is False:
                raise Exception(self.error_msg)

            range_validator: Optional[str] = None

            for attempt in range(self.MAX_RETRIES + 1):
                if self.should_stop:
                    raise RuntimeError("Download stopped")

                headers = {}
                offset = int(self.downloaded_file_size)
                if offset > 0:
                    headers["Range"] = f"bytes={offset}-"
                    if range_validator:
                        headers["If-Range"] = range_validator

                try:
                    with SESSION.get(self.url, stream=True, timeout=self.STREAM_TIMEOUT, headers=headers) as response:
                        if response.status_code == 416:
                            if self.total_file_size > 0 and offset == int(self.total_file_size):
                                break
                            self._reset_transfer()
                            range_validator = None
                            if attempt < self.MAX_RETRIES:
                                self._sleep_before_retry(attempt)
                                continue
                            response.raise_for_status()

                        response.raise_for_status()
                        self.has_network = True

                        validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                        if response.status_code != 206 or validator:
                            range_validator = validator

                        compressed = bool(response.headers.get("Content-Encoding"))
                        file_mode = "wb"

                        if response.status_code == 206 and offset > 0:
                            parsed = self._parse_content_range(response.headers.get("Content-Range"))
                            if parsed is not None and parsed[0] == offset:
                                file_mode = "ab"
                                if parsed[1] is not None:
                                    self.total_file_size = float(parsed[1])
                            else:
                                self._reset_transfer()
                                range_validator = None
                                if attempt < self.MAX_RETRIES:
                                    self._sleep_before_retry(attempt)
                                    continue
                                raise requests.exceptions.ConnectionError(
                                    f"Server returned invalid Content-Range: {response.headers.get('Content-Range')}"
                                )
                        else:
                            if offset > 0:
                                logging.info(f"Server did not resume {self.filename} (HTTP {response.status_code}), restarting from 0")
                                self._reset_transfer()
                            if not compressed and "Content-Length" in response.headers:
                                cl = float(response.headers["Content-Length"])
                                if cl > 0:
                                    self.total_file_size = cl
                            self._check_free_space(self.total_file_size)

                        with open(self.filepath, file_mode) as file:
                            for i, chunk in enumerate(response.iter_content(self.CHUNK_SIZE)):
                                if self.should_stop:
                                    raise RuntimeError("Download stopped")
                                if not chunk:
                                    continue
                                file.write(chunk)
                                self.downloaded_file_size += len(chunk)
                                if self._checksum_storage:
                                    self._update_checksum(chunk)
                                if display_progress and i % 1600 == 0:
                                    if self.total_file_size == 0.0:
                                        print(f"Downloaded {utilities.human_fmt(self.downloaded_file_size)} of {self.filename}")
                                    else:
                                        print(f"Downloaded {self.get_percent():.2f}% of {self.filename} ({utilities.human_fmt(self.get_speed())}/s) ({self.get_time_remaining():.2f} seconds remaining)")
                            file.flush()

                        if not compressed and self.total_file_size > 0:
                            if self.downloaded_file_size < self.total_file_size:
                                raise requests.exceptions.ConnectionError(
                                    f"Incomplete transfer: received {int(self.downloaded_file_size)} of {int(self.total_file_size)} bytes"
                                )
                            if self.downloaded_file_size > self.total_file_size:
                                self._reset_transfer()
                                range_validator = None
                                raise requests.exceptions.ConnectionError(
                                    f"Corrupt transfer size: exceeded expected {int(self.total_file_size)} bytes"
                                )

                        break

                except Exception as e:
                    if self.should_stop or not self._is_retryable_exception(e) or attempt >= self.MAX_RETRIES:
                        raise
                    if not self.has_network and self.downloaded_file_size == 0 and isinstance(e, requests.exceptions.ConnectionError):
                        raise
                    logging.warning(
                        f"Download interrupted for {self.filename} at {int(self.downloaded_file_size)} bytes "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                    )
                    self._sleep_before_retry(attempt)

            elapsed = max(time.time() - self.start_time, 1e-6)
            self.download_complete = True
            self.status = DownloadStatus.COMPLETE
            logging.info(f"Download complete: {self.filename}")
            logging.info("Stats:")
            logging.info(f"- Downloaded size: {utilities.human_fmt(self.downloaded_file_size)}")
            logging.info(f"- Time elapsed: {elapsed:.2f} seconds")
            logging.info(f"- Speed: {utilities.human_fmt(self.downloaded_file_size / elapsed)}/s")
            logging.info(f"- Location: {self.filepath}")
            if self._checksum_storage:
                self.checksum = self._checksum_storage.hexdigest()
                logging.info(f"Checksum: {self.checksum}")

        except Exception as e:
            self.error = True
            self.error_msg = str(e)
            self.download_complete = False
            self.status = DownloadStatus.ERROR
            self._cleanup_partial_file()
            logging.error(f"Error downloading {self.url}: {self.error_msg}")
        finally:
            atexit.unregister(self.stop)
            utilities.enable_sleep_after_running()


    def get_percent(self) -> float:
        """
        Query the download percent

        Returns:
            float: The download percent, or -1 if unknown
        """

        if self.total_file_size == 0.0:
            return -1
        return self.downloaded_file_size / self.total_file_size * 100


    def get_speed(self) -> float:
        """
        Query the download speed

        Returns:
            float: The download speed in bytes per second
        """

        return self.downloaded_file_size / max(time.time() - self.start_time, 1e-6)


    def get_time_remaining(self) -> float:
        """
        Query the time remaining for the download

        Returns:
            float: The time remaining in seconds, or -1 if unknown
        """

        if self.total_file_size == 0.0:
            return -1
        speed = self.get_speed()
        if speed <= 0:
            return -1
        return (self.total_file_size - self.downloaded_file_size) / speed


    def get_file_size(self) -> float:
        """
        Query the file size of the file to be downloaded

        Returns:
            float: The file size in bytes, or 0.0 if unknown
        """

        return self.total_file_size


    def is_active(self) -> bool:
        """
        Query if the download is active

        Returns:
            boolean: True if active, False if completed, failed, stopped, or inactive
        """

        return self.status == DownloadStatus.DOWNLOADING


    def stop(self) -> None:
        """
        Stop the download

        If the download is active, this function will hold the thread until stopped
        """

        self.should_stop = True
        if self.active_thread and self.active_thread is not threading.current_thread():
            while self.active_thread.is_alive():
                time.sleep(0.1)