"""Thin HTTP client for the server API (Python 3.6, `requests`)."""
import json

from edgeface.common.log import get_logger

LOG = get_logger("sync.client")

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0


class ServerError(Exception):
    """Any answer the client cannot use: network failure, 4xx, 5xx, bad JSON."""

    def __init__(self, message, status=None, retryable=True):
        super(ServerError, self).__init__(message)
        self.status = status
        self.retryable = retryable


class ServerClient(object):
    def __init__(self, base_url, token, device_id, verify=True,
                 connect_timeout=DEFAULT_CONNECT_TIMEOUT, read_timeout=DEFAULT_READ_TIMEOUT):
        import requests

        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.verify = verify
        self.timeout = (connect_timeout, read_timeout)
        self._session = requests.Session()
        self._session.headers.update({"Authorization": "Bearer " + (token or ""),
                                      "User-Agent": "edgeface-sync/1.0"})

    def close(self):
        self._session.close()

    def _request(self, method, path, **kwargs):
        import requests

        url = self.base_url + path
        try:
            response = self._session.request(method, url, timeout=self.timeout,
                                             verify=self.verify, **kwargs)
        except requests.RequestException as exc:
            raise ServerError("{}: {}".format(type(exc).__name__, exc), retryable=True)
        if response.status_code >= 500:
            raise ServerError("server error {}".format(response.status_code),
                              status=response.status_code, retryable=True)
        if response.status_code in (401, 403):
            # A bad token will not fix itself by retrying sooner; log loudly.
            raise ServerError("authentication rejected ({})".format(response.status_code),
                              status=response.status_code, retryable=False)
        if response.status_code >= 400:
            raise ServerError("request rejected {}: {}".format(response.status_code,
                                                               response.text[:200]),
                              status=response.status_code, retryable=False)
        return response

    def _json(self, response):
        try:
            return response.json()
        except ValueError:
            raise ServerError("server returned invalid JSON", retryable=True)

    # ------------------------------------------------------------------ endpoints
    def post_events(self, events):
        body = {"device_id": self.device_id, "events": events}
        return self._json(self._request("POST", "/api/v1/events", data=json.dumps(body),
                                        headers={"Content-Type": "application/json"}))

    def get_gallery(self, date=None, since_version=0, recognizer_sha256=None):
        params = {"since_version": since_version}
        if date:
            params["date"] = date
        if recognizer_sha256:
            params["recognizer_sha256"] = recognizer_sha256
        return self._json(self._request("GET", "/api/v1/gallery", params=params))

    def get_revocations(self, since=0.0):
        return self._json(self._request("GET", "/api/v1/revocations", params={"since": since}))

    def get_latest_bundle(self):
        try:
            return self._json(self._request("GET", "/api/v1/bundles/latest"))
        except ServerError as exc:
            if exc.status == 404:
                return None
            raise

    def download(self, path, destination):
        response = self._request("GET", path, stream=True)
        with open(destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
        return destination

    def heartbeat(self, **fields):
        return self._json(self._request("POST", "/api/v1/devices/heartbeat",
                                        data=json.dumps(fields),
                                        headers={"Content-Type": "application/json"}))
