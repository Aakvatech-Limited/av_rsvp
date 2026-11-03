import unittest

from av_rsvp.questions import FORM_SECTIONS, choices, hidden_sections, section_order, validate_answers, validate_questions


class OptionalQuestions(unittest.TestCase):
    def setUp(self):
        self.questions = [
            dict(
                question_key="transport",
                question_label="Transport",
                question_type="Select",
                options="Bus\r\nCar",
            ),
            dict(question_key="note", question_label="Note", question_type="Long Text"),
            dict(question_key="contact", question_label="Contact me", question_type="Check"),
        ]

    def test_blank_and_omitted_answers_are_optional(self):
        validate_questions(self.questions)
        self.assertEqual(validate_answers(self.questions, {}), {})
        self.assertEqual(validate_answers(self.questions, {"transport": ""}), {"transport": ""})
        self.assertEqual(
            validate_answers(self.questions, {"transport": "Bus", "contact": "1"}),
            {"transport": "Bus", "contact": "1"},
        )

    def test_rejects_unknown_keys_choices_and_malformed_values(self):
        for answers in [{"foreign": "x"}, {"transport": "Train"}, {"contact": "yes"}, {"note": {}}, []]:
            with self.assertRaises(ValueError):
                validate_answers(self.questions, answers)
        with self.assertRaises(ValueError):
            validate_answers(self.questions, {"note": "x" * 1001})

    def test_reordering_does_not_change_answer_identity(self):
        answers = {"transport": "Car", "note": "Hello"}
        self.assertEqual(
            validate_answers(self.questions, answers),
            validate_answers(list(reversed(self.questions)), answers),
        )

    def test_configuration_limits_and_duplicates(self):
        self.assertEqual(choices("Vegetarian\r\n\r\nStandard"), ["Vegetarian", "Standard"])
        for questions in [
            self.questions * 2,
            [dict(question_key="x", question_label="", question_type="Text")],
            [dict(question_key="x", question_label="Q", question_type="Select", options="")],
        ]:
            with self.assertRaises(ValueError):
                validate_questions(questions)
        with self.assertRaises(ValueError):
            choices("Bus\nBus")


class FormSectionOrder(unittest.TestCase):
    def test_default_and_partial_order_preserve_all_sections(self):
        self.assertEqual(section_order([]), FORM_SECTIONS)
        ordered = section_order([{"section": "Response"}, {"section": "Contact Details"}])
        self.assertEqual(ordered[:3], ["Event Information", "Response", "Contact Details"])
        self.assertEqual(set(ordered), set(FORM_SECTIONS))
        self.assertEqual(
            section_order([{"section": name} for name in [*FORM_SECTIONS[1:], "Event Information"]])[-1],
            "Event Information",
        )

    def test_hidden_sections_follow_explicit_row_flags(self):
        rows = [{"section": "Message to Organiser", "hide": 1}, {"section": "Event Information", "hide": 0}]
        self.assertEqual(hidden_sections(rows), ["Message to Organiser"])
        self.assertEqual(hidden_sections([]), [])

    def test_unknown_and_duplicate_sections_are_rejected(self):
        for rows in [[{"section": "Unknown"}], [{"section": "Response"}] * 2]:
            with self.assertRaises(ValueError):
                section_order(rows)
