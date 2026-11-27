import json
import logging
from collections.abc import Callable
from collections.abc import MutableMapping
from functools import partial
from typing import Any
from typing import cast

from PyQt6.QtCore import QByteArray
from PyQt6.QtCore import QIODevice
from PyQt6.QtCore import QObject
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import QUrlQuery
from PyQt6.QtNetwork import QHttpMultiPart
from PyQt6.QtNetwork import QNetworkAccessManager
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtNetwork import QNetworkRequest

from src.config import Settings
from src.oauth.oauth_flow import OAuth2Flow
from src.oauth.oauth_flow import OAuth2FlowInstance

logger = logging.getLogger(__name__)


type QueryOptions = MutableMapping[str, str | float]


DO_NOT_ENCODE = QByteArray(b":/?&=.,")


def _do_nothing(*args: Any, **kwargs: Any) -> None:
    pass


class JsonApiBase(QObject):
    def __init__(self, route: str = "") -> None:
        super().__init__()
        self.route = route
        self.host_config_key = ""
        self.api = ApiAccessManagerInstance

    def _decode_and_handle(
        self,
        handler: Callable[[dict[str, Any]], Any],
    ) -> Callable[[QNetworkReply], None]:
        def handle(reply: QNetworkReply) -> None:
            handler(self.decode_reply(reply))
        return handle

    def decode_reply(self, reply: QNetworkReply) -> dict[str, Any]:
        if message_bytes := reply.readAll().data():
            return cast(dict[str, Any], json.loads(message_bytes.decode("utf-8")))
        else:
            return {}

    def build_query_url(self, query_dict: QueryOptions) -> QUrl:
        query = QUrlQuery()
        for key, value in query_dict.items():
            query.addQueryItem(key, str(value))
        stringQuery = query.toString(QUrl.ComponentFormattingOption.FullyDecoded)
        percentEncodedByteArrayQuery = QUrl.toPercentEncoding(
            stringQuery,
            exclude=DO_NOT_ENCODE,
        )
        percentEncodedStrQuery = percentEncodedByteArrayQuery.data().decode()
        url = self._get_host_url().resolved(QUrl(self.route))
        url.setQuery(percentEncodedStrQuery)
        return url

    def _get_host_url(self) -> QUrl:
        return QUrl(Settings.get(self.host_config_key))

    def _url_from_endpoint(self, endpoint: str) -> QUrl:
        return self._get_host_url().resolved(QUrl(endpoint))

    def get(
        self,
        query_or_path: QueryOptions | str,
        response_handler: Callable[[dict[str, Any]], None],
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
        *,
        authorize: bool = True,
    ) -> QNetworkReply:
        if isinstance(query_or_path, str):
            url = self._url_from_endpoint(query_or_path)
        else:
            url = self.build_query_url(query_or_path)

        return self.api.get(
            url,
            self._decode_and_handle(response_handler),
            error_handler,
            authorize=authorize,
        )

    def post(
        self,
        endpoint: str,
        data: QByteArray | QIODevice | QHttpMultiPart,
        response_handler: Callable[[dict[str, Any]], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
    ) -> QNetworkReply:
        return self.api.post(
            self._url_from_endpoint(endpoint),
            data,
            self._decode_and_handle(response_handler),
            error_handler,
        )

    def delete(
        self,
        endpoint: str,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
    ) -> QNetworkReply:
        url = self._url_from_endpoint(endpoint)
        return self.api.delete(url, response_handler, error_handler)

    def patch(
        self,
        endpoint: str,
        data: QByteArray,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
        patch_property: Any | None = None,
    ) -> QNetworkReply:
        return self.api.patch(
            self._url_from_endpoint(endpoint),
            data,
            response_handler,
            error_handler,
            patch_property,
        )


class ApiAccessManager(QObject):
    oauth: OAuth2Flow = OAuth2FlowInstance

    def __init__(self) -> None:
        super().__init__()
        self.manager: QNetworkAccessManager = QNetworkAccessManager()
        self.manager.finished.connect(self.on_request_finished)
        self.handlers: dict[QNetworkReply, Callable[[QNetworkReply], Any]] = {}
        self.error_handlers: dict[QNetworkReply, Callable[[QNetworkReply], Any]] = {}

    def prepare_request(self, url: QUrl | None) -> QNetworkRequest:
        request = QNetworkRequest(url) if url else QNetworkRequest()
        # last 2 args are unused, but for some reason they are required
        self.oauth.prepareRequest(request, QByteArray(), QByteArray())
        return request

    def get(
        self,
        url: QUrl,
        response_handler: Callable[[QNetworkReply], None],
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
        *,
        authorize: bool = True,
    ) -> QNetworkReply:
        auth_status = "" if authorize else "unauthorized"
        logger.debug("Sending %s GET API request with URL: %s", auth_status, url.toString())
        if authorize:
            reply = self.manager.get(self.prepare_request(url))
        else:
            reply = self.manager.get(QNetworkRequest(url))

        if reply is None:
            logger.error("Error sending GET request to: '%s'", url.toString())
            raise RuntimeError("QNetworkAccessManager failed to create a QNetworkReply instance!")
        self.handlers[reply] = response_handler
        self.error_handlers[reply] = error_handler
        return reply

    def post(
        self,
        url: QUrl,
        data: QByteArray | QIODevice | QHttpMultiPart,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
    ) -> QNetworkReply:
        logger.debug("Sending POST API request with URL: %s", url.toString())
        request = self.prepare_request(url)
        if isinstance(data, QByteArray):
            request.setRawHeader(b"Content-Type", b"application/vnd.api+json;charset=utf-8")
        reply = self.manager.post(request, data)
        if reply is None:
            logger.error("Error sending POST request to: '%s' with %s", url.toString(), data.data())
            raise RuntimeError("QNetworkAccessManager failed to create a QNetworkReply instance!")
        self.handlers[reply] = response_handler
        self.error_handlers[reply] = error_handler
        return reply

    def delete(
        self,
        url: QUrl,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
    ) -> QNetworkReply:
        logger.debug("Sending DELETE API request with URL: %s", url.toString())
        request = self.prepare_request(url)
        reply = self.manager.deleteResource(request)
        if reply is None:
            logger.error("Error sending DELETE request to: %s", url.toString())
            raise RuntimeError("QNetworkAccessManager failed to create a QNetworkReply instance!")
        self.handlers[reply] = response_handler
        self.error_handlers[reply] = error_handler
        return reply

    def patch(
        self,
        url: QUrl,
        data: QByteArray,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
        patch_property: Any | None = None,
    ) -> QNetworkReply:
        logger.debug("Sending PATCH API request with URL: %s", url.toString())
        request = self.prepare_request(url)
        request.setRawHeader(b"Content-Type", b"application/vnd.api+json;charset=utf-8")
        reply = self.manager.sendCustomRequest(request, b"PATCH", data)

        if reply is None:
            logger.error("Error sending PATCH request to: %s", url.toString())
            raise RuntimeError("QNetworkAccessManager failed to create a QNetworkReply instance!")

        reply.setProperty("patch_property", patch_property)
        self.handlers[reply] = response_handler
        self.error_handlers[reply] = error_handler
        return reply

    def put(
        self,
        url: QUrl,
        data: QByteArray | QIODevice,
        response_handler: Callable[[QNetworkReply], None] = _do_nothing,
        error_handler: Callable[[QNetworkReply], None] = _do_nothing,
        *,
        authorize: bool = True,
    ) -> QNetworkReply:
        auth_status = "" if authorize else "unauthorized"
        logger.debug("Sending %s PUT API request with URL: %s", auth_status, url.toString())

        if authorize:
            request = self.prepare_request(url)
        else:
            request = QNetworkRequest(url)

        reply = self.manager.put(request, data)
        if reply is None:
            logger.error("Error sending PUT request to: %s", url.toString())
            raise RuntimeError("QNetworkAccessManager failed to create a QNetworkReply instance!")

        self.handlers[reply] = response_handler
        self.error_handlers[reply] = error_handler
        return reply

    def on_request_finished(self, reply: QNetworkReply) -> None:
        if reply.error() != QNetworkReply.NetworkError.NoError:
            details = reply.peek(reply.bytesAvailable())
            logger.error(
                "API request error. URL: %s. Error: %s (%s). [%s]",
                reply.url().url(),
                reply.error(),
                reply.errorString(),
                details.decode() if details else "",
            )
            self.error_handlers[reply](reply)
        else:
            url = reply.request().url().toString()
            logger.debug("%s operation succeeded: %s", reply.operation(), url)
            self.handlers[reply](reply)

        self.handlers.pop(reply)
        self.error_handlers.pop(reply)
        reply.deleteLater()

    def abort(self) -> None:
        for reply in self.handlers.copy():
            try:
                reply.abort()
            except RuntimeError as e:
                # wrapped C++ object has been deleted: may happen when dialog window
                # which performed some network requests was closed before they finished
                logger.warning("%s", e)


ApiAccessManagerInstance = ApiAccessManager()


class ReplyGroup:
    def __init__(self, owner: QObject) -> None:
        self._replies: set[QNetworkReply] = set()
        owner.destroyed.connect(lambda: self.abort())

    def add(self, reply: QNetworkReply) -> None:
        self._replies.add(reply)
        reply.finished.connect(partial(self._replies.discard, reply))

    def abort(self) -> None:
        for reply in tuple(self._replies):
            try:
                reply.abort()
            except RuntimeError:
                pass
        self._replies.clear()
