from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from app.i18n import t

Headers = list[tuple[str, str]]


def register(app: Flask) -> None:
    app.register_error_handler(404, _not_found)
    app.register_error_handler(500, _server_error)
    app.register_error_handler(CSRFError, _csrf_error)
    app.register_error_handler(HTTPException, _http_error)


def _not_found(error: HTTPException) -> tuple[str, int, Headers]:
    return _render(t("errors.not_found_title"), t("errors.not_found_text"), error)


def _server_error(_error: Exception) -> tuple[str, int, Headers]:
    return _render(t("errors.server_error_title"), t("errors.server_error_text"))


def _csrf_error(error: CSRFError) -> tuple[str, int, Headers]:
    return _render(t("errors.csrf_title"), t("errors.csrf_text"), error)


def _http_error(error: HTTPException) -> tuple[str, int, Headers]:
    code = error.code or 500
    return _render(t("errors.generic_title"), t("errors.generic_text", code=code), error)


def _render(title: str, text: str, error: HTTPException | None = None) -> tuple[str, int, Headers]:
    status = (error.code or 500) if error else 500
    # Keep protocol headers such as Allow (405) or Retry-After (429).
    headers = [
        (name, value)
        for name, value in (error.get_headers() if error else [])
        if name.lower() != "content-type"
    ]
    headers.append(("Vary", "HX-Request"))
    # Plain HTMX requests swap the response into the page, so they only get the message.
    # Boosted navigation expects a whole page.
    fragment = request.headers.get("HX-Request") and not request.headers.get("HX-Boosted")
    template = "errors/_message.html" if fragment else "errors/page.html"
    return render_template(template, title=title, text=text), status, headers
