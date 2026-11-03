import unittest

from av_rsvp.text import event_text


class EventText(unittest.TestCase):
    def test_crlf_lf_and_blank_lines(self):
        self.assertEqual(event_text("First\r\nSecond\r\n\r\nFourth\rFifth"), "First\nSecond\n\nFourth\nFifth")

    def test_editor_paragraphs_and_breaks(self):
        self.assertEqual(
            event_text("<p>Welcome<br>Guests</p><p><br></p><p>Dinner</p>"), "Welcome\nGuests\n\nDinner"
        )
        self.assertEqual(event_text("<div>First</div><div>Second<br/>Third</div>"), "First\nSecond\nThird")

    def test_entities_inline_text_and_hidden_content(self):
        self.assertEqual(
            event_text("<p>Tea &amp; <b>dinner</b></p><script>alert(1)</script><style>p{}</style>"),
            "Tea & dinner",
        )
        self.assertEqual(event_text("Use &lt;name&gt; here"), "Use <name> here")

    def test_empty_description(self):
        self.assertEqual(event_text(None), "")
