"""Readable plain text for the escaped guest portal."""

from html.parser import HTMLParser


class _EventText(HTMLParser):
    blocks = {"p", "div", "li", "ul", "ol", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def boundary(self):
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag == "br":
            self.parts.append("\n")
        elif tag in self.blocks:
            self.boundary()

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
            return
        if not self.hidden and tag in self.blocks:
            self.boundary()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def event_text(value):
    """Retain CRLF, BR and editor block boundaries without rendering HTML."""
    parser = _EventText()
    parser.feed((value or "").replace("\r\n", "\n").replace("\r", "\n"))
    parser.close()
    return "".join(parser.parts).strip("\n")
