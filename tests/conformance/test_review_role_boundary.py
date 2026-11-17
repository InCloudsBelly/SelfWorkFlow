from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReviewRoleBoundaryTests(unittest.TestCase):
    def test_code_review_references_the_review_method_without_change_rules(self):
        review = (ROOT / "workflow/modules/review.md").read_text(encoding="utf-8")
        routes = re.findall(r"\]\(([^)\n]+)\)", review)
        route = "../../skills/code-quality/references/review-rules.md"
        self.assertIn(route, routes)
        method = (ROOT / "workflow/modules" / route).resolve()
        self.assertTrue(method.is_file())
        links = re.findall(r"\]\(([^)\n]+)\)", method.read_text(encoding="utf-8"))
        forbidden = {
            (ROOT / "skills/code-quality/references/change-rules.md").resolve(),
            (ROOT / "workflow/modules/review.md").resolve(),
        }
        for link in links:
            if re.match(r"[a-z][\w+.-]*:|#", link, re.I):
                continue
            target = (method.parent / link.split("#", 1)[0]).resolve()
            with self.subTest(link=link):
                self.assertTrue(target.is_relative_to(ROOT))
                self.assertTrue(target.is_file())
                self.assertNotIn(target, forbidden)


if __name__ == "__main__":
    unittest.main()
