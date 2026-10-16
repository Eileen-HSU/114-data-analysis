import json
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(__file__))

from services.ppt_survey_ai_service import (  # noqa: E402
    INSUFFICIENT_CONTENT_MESSAGE,
    PDF_TEXT_EXTRACTION_FAILED_MESSAGE,
    PptSurveyAiError,
    _call_gemini,
    _extract_pdf_page_text,
    generate_survey_from_material,
)


SUFFICIENT_PDF_TEXT = """
Course overview: the material introduces project planning, user research, and prototype validation.
Students compare survey requirements, define target participants, and summarize feedback goals.
The document explains how collected responses should help improve teaching activities and system usability.
It also describes expected learning outcomes, collaboration checkpoints, and reflection after the final presentation.
"""


class FakeGeminiPart:
    calls = []

    @classmethod
    def from_bytes(cls, **kwargs):
        cls.calls.append(kwargs)
        return {"part": kwargs}


class FakeGeminiTypes:
    Part = FakeGeminiPart

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs


def fake_image_part(page_number):
    return {
        "part": {
            "data": f"jpeg page {page_number}".encode("utf-8"),
            "mime_type": "image/jpeg",
        }
    }


def valid_gemini_draft():
    return {
        "title": "scan survey",
        "description": "",
        "questions": [
            {"id": "q1", "type": "short", "title": "What did you learn?", "required": True, "options": []},
            {"id": "q2", "type": "rating", "title": "Rate the clarity.", "required": True, "options": []},
        ],
    }


class FakeGeminiResponse:
    def __init__(self, text):
        self.text = text


class FakeGeminiApiError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


class FakeGeminiModels:
    def __init__(self, owner, api_key):
        self.owner = owner
        self.api_key = api_key

    def generate_content(self, **kwargs):
        self.owner.calls.append({"api_key": self.api_key, **kwargs})
        outcome = self.owner.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeGeminiResponse(outcome)


class FakeGeminiClient:
    def __init__(self, owner, api_key, http_options=None):
        self.models = FakeGeminiModels(owner, api_key)
        self.http_options = http_options


class FakeGeminiModule:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def Client(self, api_key, http_options=None):
        return FakeGeminiClient(self, api_key, http_options=http_options)


class PptSurveyAiServiceFallbackTest(unittest.TestCase):
    def test_pdf_page_text_extraction_success(self):
        class FakePage:
            def extract_text(self, **_options):
                return "  Course content about surveys and reflection.  "

        self.assertEqual(
            _extract_pdf_page_text(FakePage()),
            "Course content about surveys and reflection.",
        )

    @patch("services.ppt_survey_ai_service.PPT_SURVEY_GEMINI_MODELS", ("gemini-3.5-flash",))
    @patch("services.ppt_survey_ai_service._get_ppt_survey_api_keys")
    @patch("services.ppt_survey_ai_service._load_genai_types")
    def test_call_gemini_continues_after_forbidden_and_returns_schema(
        self,
        load_genai_types,
        get_ppt_survey_api_keys,
    ):
        fake_genai = FakeGeminiModule([
            FakeGeminiApiError("forbidden", 403),
            '{"title":"scan survey","questions":[{"type":"short","title":"Explain the topic"}]}',
        ])
        load_genai_types.return_value = (fake_genai, FakeGeminiTypes)
        get_ppt_survey_api_keys.return_value = (
            ("primary", "primary-test-key"),
            ("fallback", "fallback-test-key"),
        )

        raw = _call_gemini(["prompt"])

        self.assertEqual(raw["title"], "scan survey")
        self.assertEqual(len(fake_genai.calls), 2)
        self.assertEqual(fake_genai.calls[0]["api_key"], "primary-test-key")
        self.assertEqual(fake_genai.calls[1]["api_key"], "fallback-test-key")
        self.assertEqual(fake_genai.calls[1]["model"], "gemini-3.5-flash")
        self.assertEqual(fake_genai.calls[1]["contents"], ["prompt"])
        self.assertEqual(
            fake_genai.calls[1]["config"].kwargs["response_mime_type"],
            "application/json",
        )

    @patch("services.ppt_survey_ai_service.PPT_SURVEY_GEMINI_MODELS", ("gemini-3.5-flash",))
    @patch("services.ppt_survey_ai_service._get_ppt_survey_api_keys")
    @patch("services.ppt_survey_ai_service._load_genai_types")
    def test_call_gemini_mixed_model_and_auth_failures_are_not_all_auth(
        self,
        load_genai_types,
        get_ppt_survey_api_keys,
    ):
        fake_genai = FakeGeminiModule([
            FakeGeminiApiError("model not found", 404),
            FakeGeminiApiError("forbidden", 403),
        ])
        load_genai_types.return_value = (fake_genai, FakeGeminiTypes)
        get_ppt_survey_api_keys.return_value = (
            ("primary", "primary-test-key"),
            ("fallback", "fallback-test-key"),
        )

        with self.assertRaises(PptSurveyAiError) as raised:
            _call_gemini(["prompt"])

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(str(raised.exception), "PPT survey Gemini failed across model/key fallbacks.")
        self.assertEqual(
            [failure["status_code"] for failure in raised.exception.gemini_failures],
            [404, 403],
        )

    @patch("services.ppt_survey_ai_service.time.sleep")
    @patch(
        "services.ppt_survey_ai_service.PPT_SURVEY_GEMINI_MODELS",
        ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"),
    )
    @patch("services.ppt_survey_ai_service._get_ppt_survey_api_keys")
    @patch("services.ppt_survey_ai_service._load_genai_types")
    @patch("services.ppt_survey_ai_service._render_pdf_page_image_parts")
    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service._extract_scanned_pdf_ocr_text")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._load_genai_client")
    def test_image_pdf_503_retries_then_uses_next_model_and_returns_draft(
        self,
        load_genai_client,
        extract_document_text,
        extract_scanned_pdf_ocr_text,
        inspect_pdf_content,
        render_pdf_page_image_parts,
        load_genai_types,
        get_ppt_survey_api_keys,
        sleep,
    ):
        FakeGeminiPart.calls = []
        fake_genai = FakeGeminiModule([
            FakeGeminiApiError("503 unavailable", 503),
            FakeGeminiApiError("503 unavailable", 503),
            FakeGeminiApiError("503 unavailable", 503),
            json.dumps(valid_gemini_draft()),
        ])
        load_genai_client.return_value = (object(), FakeGeminiTypes)
        load_genai_types.return_value = (fake_genai, FakeGeminiTypes)
        get_ppt_survey_api_keys.return_value = (("primary", "test-key"),)
        extract_document_text.return_value = ""
        extract_scanned_pdf_ocr_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 1, "text_layer_pages": 0, "image_pages": 1}
        render_pdf_page_image_parts.return_value = [fake_image_part(1)]

        draft = generate_survey_from_material(
            "scan.pdf",
            b"%PDF mock",
            {"typeCounts": {"short": 1, "rating": 1}},
        )

        self.assertEqual(
            [call["model"] for call in fake_genai.calls],
            ["gemini-3.8-flash"] * 3 + ["gemini-3.6-flash"],
        )
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(fake_genai.calls[-1]["contents"][0]["part"]["mime_type"], "image/jpeg")
        self.assertEqual(draft["title"], "scan survey")
        self.assertEqual([question["type"] for question in draft["questions"]], ["short", "rating"])
        self.assertTrue(all("id" in question for question in draft["questions"]))

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

    @patch("services.ppt_survey_ai_service._render_pdf_page_image_parts")
    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service._extract_scanned_pdf_ocr_text")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._load_genai_client")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_scanned_pdf_ocr_empty_renders_pages_for_image_analysis(
        self,
        call_gemini,
        load_genai_client,
        extract_document_text,
        extract_scanned_pdf_ocr_text,
        inspect_pdf_content,
        render_pdf_page_image_parts,
    ):
        FakeGeminiPart.calls = []
        extract_document_text.return_value = ""
        extract_scanned_pdf_ocr_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 2}
        load_genai_client.return_value = (object(), FakeGeminiTypes)
        render_pdf_page_image_parts.return_value = [fake_image_part(1), fake_image_part(2)]
        call_gemini.return_value = valid_gemini_draft()

        draft = generate_survey_from_material("scan.pdf", b"%PDF mock", {})

        self.assertEqual(draft["title"], "scan survey")
        self.assertEqual([q["type"] for q in draft["questions"]], ["short", "rating"])
        extract_scanned_pdf_ocr_text.assert_called_once_with(b"%PDF mock")
        load_genai_client.assert_called_once()
        render_pdf_page_image_parts.assert_called_once_with(b"%PDF mock", FakeGeminiTypes)
        call_gemini.assert_called_once()
        contents = call_gemini.call_args.args[0]
        self.assertEqual(contents[0]["part"]["mime_type"], "image/jpeg")
        self.assertEqual(contents[1]["part"]["mime_type"], "image/jpeg")
        self.assertIn("scan.pdf", contents[2])
        self.assertEqual(FakeGeminiPart.calls, [])

    @patch("services.ppt_survey_ai_service._render_pdf_page_image_parts")
    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service._extract_scanned_pdf_ocr_text")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._load_genai_client")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_scanned_pdf_image_analysis_failure_propagates_error(
        self,
        call_gemini,
        load_genai_client,
        extract_document_text,
        extract_scanned_pdf_ocr_text,
        inspect_pdf_content,
        render_pdf_page_image_parts,
    ):
        extract_document_text.return_value = ""
        extract_scanned_pdf_ocr_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 2}
        load_genai_client.return_value = (object(), FakeGeminiTypes)
        render_pdf_page_image_parts.return_value = [fake_image_part(1)]
        call_gemini.side_effect = PptSurveyAiError("image analysis failed", 502)

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material("scan.pdf", b"%PDF mock", {})

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(str(raised.exception), "image analysis failed")
        render_pdf_page_image_parts.assert_called_once_with(b"%PDF mock", FakeGeminiTypes)
        call_gemini.assert_called_once()

    @patch("services.ppt_survey_ai_service._render_pdf_page_image_parts")
    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service._extract_scanned_pdf_ocr_text")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._load_genai_client")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_scanned_pdf_image_analysis_403_does_not_loop_in_generation_flow(
        self,
        call_gemini,
        load_genai_client,
        extract_document_text,
        extract_scanned_pdf_ocr_text,
        inspect_pdf_content,
        render_pdf_page_image_parts,
    ):
        extract_document_text.return_value = ""
        extract_scanned_pdf_ocr_text.return_value = ""
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 2}
        load_genai_client.return_value = (object(), FakeGeminiTypes)
        render_pdf_page_image_parts.return_value = [fake_image_part(1)]
        call_gemini.side_effect = PptSurveyAiError("forbidden", 403)

        with self.assertRaises(PptSurveyAiError) as raised:
            generate_survey_from_material("scan.pdf", b"%PDF mock", {})

        self.assertEqual(raised.exception.status_code, 403)
        render_pdf_page_image_parts.assert_called_once_with(b"%PDF mock", FakeGeminiTypes)
        call_gemini.assert_called_once()

    @patch("services.ppt_survey_ai_service._inspect_pdf_content")
    @patch("services.ppt_survey_ai_service._extract_scanned_pdf_ocr_text")
    @patch("services.ppt_survey_ai_service.extract_document_text")
    @patch("services.ppt_survey_ai_service._call_gemini")
    def test_scanned_pdf_ocr_text_uses_existing_generation_flow(
        self,
        call_gemini,
        extract_document_text,
        extract_scanned_pdf_ocr_text,
        inspect_pdf_content,
    ):
        extract_document_text.return_value = ""
        extract_scanned_pdf_ocr_text.return_value = SUFFICIENT_PDF_TEXT
        inspect_pdf_content.return_value = {"pages": 2, "text_layer_pages": 0, "image_pages": 2}
        call_gemini.side_effect = PptSurveyAiError("forbidden", 403)

        draft = generate_survey_from_material(
            "scan.pdf",
            b"%PDF mock",
            {"typeCounts": {"short": 1, "rating": 1}},
        )

        self.assertEqual([q["type"] for q in draft["questions"]], ["short", "rating"])
        self.assertIn("project planning", draft["questions"][0]["title"])
        extract_scanned_pdf_ocr_text.assert_called_once_with(b"%PDF mock")
        call_gemini.assert_called_once()
        self.assertEqual(call_gemini.call_args.kwargs, {"stop_on_status_codes": {403}})

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
