from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin


@dataclass
class HtmlForm:
    action: str
    method: str = "GET"
    fields: dict[str, str] = field(default_factory=dict)

    def absolute_action(self, base_url: str) -> str:
        return urljoin(base_url, self.action)


class FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[HtmlForm] = []
        self._current: HtmlForm | None = None
        self._current_select_name: str | None = None
        self._current_select_value: str | None = None
        self._current_textarea_name: str | None = None
        self._textarea_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "form":
            self._current = HtmlForm(
                action=attrs_dict.get("action", ""),
                method=(attrs_dict.get("method") or "GET").upper(),
            )
            return

        if self._current is None:
            return

        tag_name = tag.lower()

        if tag_name == "input":
            name = attrs_dict.get("name")
            if name:
                self._current.fields[name] = attrs_dict.get("value", "")
            return

        if tag_name == "select":
            self._current_select_name = attrs_dict.get("name")
            self._current_select_value = None
            return

        if tag_name == "option" and self._current_select_name:
            if "selected" in attrs_dict:
                self._current_select_value = attrs_dict.get("value", "")
            return

        if tag_name == "textarea":
            self._current_textarea_name = attrs_dict.get("name")
            self._textarea_chunks = []
            return

    def handle_data(self, data: str) -> None:
        if self._current_textarea_name:
            self._textarea_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()

        if tag_name == "select" and self._current is not None and self._current_select_name:
            self._current.fields[self._current_select_name] = self._current_select_value or ""
            self._current_select_name = None
            self._current_select_value = None
            return

        if tag_name == "textarea" and self._current is not None and self._current_textarea_name:
            self._current.fields[self._current_textarea_name] = "".join(self._textarea_chunks)
            self._current_textarea_name = None
            self._textarea_chunks = []
            return

        if tag_name == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


def parse_forms(html: str) -> list[HtmlForm]:
    parser = FormParser()
    parser.feed(html)
    return parser.forms


def find_form(forms: list[HtmlForm], required_fields: set[str]) -> HtmlForm:
    for form in forms:
        if required_fields.issubset(form.fields.keys()):
            return form
    raise RuntimeError(f"No encuentro formulario con campos: {', '.join(sorted(required_fields))}")
