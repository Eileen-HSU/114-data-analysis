import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

from services.ppt_survey_ai_service import (  # noqa: E402
    INSUFFICIENT_CONTENT_MESSAGE,
    PDF_TEXT_EXTRACTION_FAILED_MESSAGE,
    PptSurveyAiError,
    SCANNED_PDF_UNSUPPORTED_MESSAGE,
    _extract_pdf_page_text,
    generate_survey_from_material,
)


SUFFICIENT_PDF_TEXT = """
Course overview: the material introduces project planning, user research, and prototype validation.
Students compare survey requirements, define target participants, and summarize feedback goals.
The document explains how collected responses should help improve teaching activities and system usability.
It also describes expected learning outcomes, collaboration checkpoints, and reflection after the final presentation.
"""


class PptSurveyAiServiceFallbackTest(unittest.TestCase):
    def test_pdf_page_text_extraction_success(self):
        class FakePage:
            def extract_text(self, **_options):
                return "  Course content about surveys and reflection.  "

        self.assertEqual(
            _extract_pdf_page_text(FakePage()),
            "Course content about surveys and reflection.",
        )

    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_403_uses_rule_based_fallback(self, call_gemini, extract_document_text):
        extract_document_text.return_value = SUFFICIENT_PDF_TEXT
        call_gemini.side_effect = PptSurveyAiError("forbidden", 403)

        draft = generate_survey_from_material(
            "course.pdf",
            b"%PDF mock",
            {"typeCounts": {"short": 2, "rating": 1}},
        )

        self.assertEqual(draft["title"], "course survey")
        self.assertEqual(len(draft["questions"]), 3)
        self.assertEqual([q["type"] for q in draft["questions"]], ["short", "short", "rating"])
        self.assertTrue(all(q["required"] for q in draft["questions"]))
        self.assertTrue(all(q["options"] == [] for q in draft["questions"]))
        self.assertIn("project planning", draft["questions"][0]["title"])
        call_gemini.assert_called_once()
        self.assertEqual(call_gemini.call_args.kwargs, {"stop_on_status_codes": {403}})

    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_non_403_error_does_not_use_fallback(self, call_gemini, extract_document_text):
        extract_document_text.return_value = SUFFICIENT_PDF_TEXT
        call_gemini.side_effect = PptSurveyAiError("not found", 404)

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material(
                "course.pdf",
                b"%PDF mock",
                {"typeCounts": {"short": 2, "rating": 1}},
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(str(raised.exception), "not found")
        call_gemini.assert_called_once()

    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_insufficient_text_fails_without_gemini_call(self, call_gemini, extract_document_text):
        extract_document_text.return_value = "Poster title\n2026/10/14\nhttps://example.com"

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material(
                "poster.pdf",
                b"%PDF mock",
                {"typeCounts": {"short": 1, "rating": 0}},
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(str(raised.exception), INSUFFICIENT_CONTENT_MESSAGE)
        call_gemini.assert_not_called()

    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_blank_pdf_without_text_or_images_keeps_insufficient_message(
        self,
        call_gemini,
        extract_document_text,
        inspect_pdf_content,
    ):
        extract_document_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 0}

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material("blank.pdf", b"%PDF mock", {})

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(str(raised.exception), INSUFFICIENT_CONTENT_MESSAGE)
        call_gemini.assert_not_called()

    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_scanned_pdf_reports_ocr_limitation_without_gemini_call(
        self,
        call_gemini,
        extract_document_text,
        inspect_pdf_content,
    ):
        extract_document_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 2}

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material("scan.pdf", b"%PDF mock", {})

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(str(raised.exception), SCANNED_PDF_UNSUPPORTED_MESSAGE)
        call_gemini.assert_not_called()

    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_text_layer_extraction_failure_is_not_marked_insufficient(
        self,
        call_gemini,
        extract_document_text,
        inspect_pdf_content,
    ):
        extract_document_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 2, "image_pages": 0}

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material("text-layer.pdf", b"%PDF mock", {})

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(str(raised.exception), PDF_TEXT_EXTRACTION_FAILED_MESSAGE)
        call_gemini.assert_not_called()

    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_any_403_failure_uses_fallback(self, call_gemini, extract_document_text):
        extract_document_text.return_value = SUFFICIENT_PDF_TEXT
        error = PptSurveyAiError("models unavailable", 404)
        error.gemini_failures = [
            {"model": "gemini-3.5-flash", "key_role": "fallback", "status_code": 403},
            {"model": "gemini-3.8-flash", "key_role": "primary", "status_code": 404},
        ]
        call_gemini.side_effect = error

        draft = generate_survey_from_material(
            "course.pdf",
            b"%PDF mock",
            {"typeCounts": {"short": 1, "rating": 1}},
        )

        self.assertEqual([q["type"] for q in draft["questions"]], ["short", "rating"])
        self.assertEqual(len({q["title"] for q in draft["questions"]}), 2)

    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_pdf_zero_type_counts_are_normalized_before_fallback(self, call_gemini, extract_document_text):
        extract_document_text.return_value = SUFFICIENT_PDF_TEXT
        call_gemini.side_effect = PptSurveyAiError("forbidden", 403)

        draft = generate_survey_from_material(
            "course.pdf",
            b"%PDF mock",
            {
                "questionCount": 2,
                "typeCounts": {"short": 0, "rating": 0},
                "typeLimits": {"rating": False},
            },
        )

        self.assertEqual(len(draft["questions"]), 2)
        self.assertEqual([q["type"] for q in draft["questions"]], ["short", "short"])
        self.assertEqual(len({q["title"] for q in draft["questions"]}), 2)


if __name__ == "__main__":
    unittest.main()
