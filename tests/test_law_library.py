"""Meaningful parser and citation checks for the separate law library."""

import unittest

from app.law_library import article_number, explicit_references, parse_articles


class LawLibraryTests(unittest.TestCase):
    def test_chinese_article_numbers(self):
        self.assertEqual(article_number("四十四"), 44)
        self.assertEqual(article_number("一百零二"), 102)
        self.assertEqual(article_number("34"), 34)

    def test_full_article_keeps_following_paragraphs(self):
        articles = parse_articles([
            "第一章 总则", "第一条 先说明适用范围。", "第二款仍属于第一条。",
            "第二条 违反本法第一条规定的，予以处理。",
        ])
        self.assertEqual(len(articles), 2)
        self.assertIn("第二款仍属于第一条。", articles[0]["content"])
        self.assertEqual(articles[1]["chapter"], "第一章 总则")
        self.assertEqual(explicit_references(articles[1], {1, 2}), [{"to_number": 1, "evidence": "第一条"}])

    def test_external_law_article_is_not_same_law_link(self):
        article = {"article_number": 3, "article_label": "第三条",
                   "content": "第三条 依照《其他法》第一条、第二条和本法第一条执行。"}
        self.assertEqual(explicit_references(article, {1, 2, 3}), [{"to_number": 1, "evidence": "第一条"}])

    def test_incomplete_article_sequence_fails(self):
        with self.assertRaises(ValueError):
            parse_articles(["第一条 内容。", "第三条 内容。"])

    def test_heading_split_by_official_html_spans(self):
        articles = parse_articles(["第一条 内容。", "第二 条 后一条。"])
        self.assertEqual(articles[1]["article_label"], "第二条")
        self.assertTrue(articles[1]["content"].startswith("第二条 后一条。"))
        split = parse_articles(["第一条 内容。", "第二", "条 后一条。"])
        self.assertEqual(split[1]["article_number"], 2)


if __name__ == "__main__":
    unittest.main()
