import unittest

from tav_core import RequestError, evaluate


class EvaluateTests(unittest.TestCase):
    def test_all_concepts_and_caller_synonym(self):
        result = evaluate({
            "rubric": {
                "required_concepts": ["isolation", "lockout tag"],
                "accepted_synonyms": {"isolation": ["energy isolation"]},
                "required_count": 2,
            },
            "answer": "Apply energy isolation and attach a lockout tag.",
        })
        self.assertEqual(result["verdict"], "correct")
        self.assertEqual(result["score"], 1.0)
        self.assertTrue(result["review_required"])

    def test_wrong_number_penalizes_score(self):
        result = evaluate({
            "rubric": {
                "required_concepts": ["pressure test"],
                "numeric_requirements": [{"value": "10", "unit": "kN"}],
            },
            "answer": "Pressure test at 12 kN.",
        })
        self.assertEqual(result["score"], 0.5)
        self.assertFalse(result["numeric_checks"][0]["passed"])

    def test_rejects_unexpected_fields(self):
        with self.assertRaises(RequestError):
            evaluate({"rubric": {"required_concepts": ["A"], "accepted_synonyms": {"A": []}, "trap": "secret"}, "answer": "A"})

    def test_invalid_synonym_key_rejected(self):
        with self.assertRaises(RequestError):
            evaluate({"rubric": {"required_concepts": ["A"], "accepted_synonyms": {"B": ["C"]}}, "answer": "C"})

    def test_required_count_controls_score_denominator(self):
        result = evaluate({
            "rubric": {"required_concepts": ["alpha", "bravo", "charlie"], "required_count": 2},
            "answer": "alpha and bravo",
        })
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["verdict"], "correct")

    def test_numeric_unit_boundary_and_conflicting_values(self):
        result = evaluate({
            "rubric": {
                "required_concepts": ["test"],
                "numeric_requirements": [{"value": "10", "unit": "m"}],
            },
            "answer": "test length 10 mm",
        })
        self.assertFalse(result["numeric_checks"][0]["passed"])
        result = evaluate({
            "rubric": {
                "required_concepts": ["test"],
                "numeric_requirements": [{"value": "10", "unit": "m"}],
            },
            "answer": "test length 10 m and 12 m",
        })
        self.assertFalse(result["numeric_checks"][0]["passed"])

    def test_number_grouping_and_decimal_comma(self):
        for answer, expected in [("load 1,000 kN", "1000"), ("load 1,5 kN", "1.5")]:
            result = evaluate({
                "rubric": {
                    "required_concepts": ["load"],
                    "numeric_requirements": [{"value": expected, "unit": "kN"}],
                },
                "answer": answer,
            })
            self.assertTrue(result["numeric_checks"][0]["passed"], answer)

    def test_invalid_unicode_is_a_request_error(self):
        with self.assertRaises(RequestError):
            evaluate({"rubric": {"required_concepts": ["concept"]}, "answer": "bad \ud800"})

    def test_typo_tolerance_finds_a_short_misspelling(self):
        result = evaluate({"rubric": {"required_concepts": ["safety"]}, "answer": "safty"})
        self.assertEqual(result["matched_concepts"], ["safety"])

    def test_synonym_cannot_double_count_concepts(self):
        with self.assertRaises(RequestError):
            evaluate({
                "rubric": {
                    "required_concepts": ["alpha", "bravo"],
                    "accepted_synonyms": {"bravo": ["alpha"]},
                },
                "answer": "alpha",
            })

    def test_missing_concepts_and_required_count(self):
        result = evaluate({
            "rubric": {"required_concepts": ["alpha", "bravo", "charlie"], "required_count": 2},
            "answer": "alpha",
        })
        self.assertEqual(result["verdict"], "partial")
        self.assertEqual(result["missing_concepts"], ["bravo", "charlie"])
        self.assertTrue(result["notes"])


if __name__ == "__main__":
    unittest.main()
