import json
import unittest

from modules.Information_Gathering.Enterprise_Query.aiqicha_query import AiqichaQuery


class _DummyResponse:
    def __init__(self, html: str, url: str = "https://aiqicha.baidu.com/s?q=test&t=0"):
        self.status_code = 200
        self.text = html
        self.url = url


class _SearchHarness(AiqichaQuery):
    def __init__(self, html: str, response_url: str = "https://aiqicha.baidu.com/s?q=test&t=0"):
        self.html = html
        self.response_url = response_url
        self.opened_browser_calls = []
        self.aiqicha_cookies = {}
        self.xunkebao_cookies = {}
        self.aiqicha_cookie_raw = ""
        self.xunkebao_cookie_raw = ""
        self.debug_output_enabled = False
        self.debug_output_dir = None
        self._verification_page_capture = None

    def reload_session_cookies_from_config(self) -> None:
        return None

    def _make_request(self, method, url, status_callback=None, **kwargs):
        return _DummyResponse(self.html, self.response_url)

    def _open_with_drissionpage(self, url: str, prefix: str, cookie_str=None, **kwargs):
        self.opened_browser_calls.append((url, prefix, kwargs))
        return None


def _page_data_html(page_data: dict) -> str:
    return (
        "<html><head><script>"
        f"window.pageData = {json.dumps(page_data, ensure_ascii=False)};"
        "</script></head><body></body></html>"
    )


class AiqichaQueryTest(unittest.TestCase):
    def test_absorbed_candidates_are_reused_without_browser(self):
        query = object.__new__(AiqichaQuery)
        query.debug_output_enabled = False
        html = _page_data_html({
            "queryWord": "北京目标科技有限公司",
            "result": {
                "queryStr": "北京目标科技有限公司",
                "resultList": [],
                "absorbed": [
                    {
                        "pid": "12345",
                        "entName": "北京目标科技有限公司",
                        "legalPerson": "张三",
                    }
                ],
            },
        })

        data = query._extract_page_data(html)
        matched = query._filter_search_result_by_company_name(data, "北京目标科技有限公司")

        self.assertIsNotNone(matched)
        self.assertEqual(matched["result"]["resultList"][0]["pid"], "12345")

    def test_company_suffix_difference_still_matches(self):
        query = object.__new__(AiqichaQuery)

        self.assertTrue(
            query._is_company_name_match(
                "中基宁波集团有限公司",
                "中基宁波集团股份有限公司",
            )
        )

    def test_absorbed_suffix_difference_search_does_not_open_browser(self):
        html = _page_data_html({
            "queryWord": "中基宁波集团有限公司",
            "result": {
                "queryStr": "中基宁波集团有限公司",
                "resultList": [],
                "absorbed": [
                    {"pid": "1180744", "entName": "中基宁波集团股份有限公司"},
                    {"pid": "10001", "entName": "中基宁波有限公司"},
                    {"pid": "10002", "entName": "宁波中基国际物流有限公司"},
                ],
            },
        })
        query = _SearchHarness(html)

        result = query.search_company("中基宁波集团有限公司", max_retries=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["result"]["resultList"][0]["pid"], "1180744")
        self.assertEqual(query.opened_browser_calls, [])

    def test_search_list_mismatch_uses_browser_as_final_fallback(self):
        html = _page_data_html({
            "queryWord": "北京目标科技有限公司",
            "result": {
                "queryStr": "北京目标科技有限公司",
                "resultList": [
                    {"pid": "99999", "entName": "上海其他科技有限公司"}
                ],
            },
        })
        query = _SearchHarness(html)

        result = query.search_company("北京目标科技有限公司", max_retries=1)

        self.assertEqual(result, {})
        self.assertEqual(len(query.opened_browser_calls), 1)
        self.assertEqual(query.opened_browser_calls[0][1], "aiqicha_search_mismatch_fallback")
        self.assertTrue(query.opened_browser_calls[0][2].get("silent_if_no_verify"))

    def test_normal_page_wappass_link_does_not_open_browser_before_parsing(self):
        html = _page_data_html({
            "queryWord": "北京目标科技有限公司",
            "result": {
                "queryStr": "北京目标科技有限公司",
                "resultList": [
                    {"pid": "12345", "entName": "北京目标科技有限公司"}
                ],
            },
        }) + '<script>var loginUrl = "https://wappass.baidu.com/passport/login";</script>'
        query = _SearchHarness(html)

        result = query.search_company("北京目标科技有限公司", max_retries=1)

        self.assertIsNotNone(result)
        self.assertEqual(result["result"]["resultList"][0]["pid"], "12345")
        self.assertEqual(query.opened_browser_calls, [])

    def test_verification_gate_still_opens_browser(self):
        html = "<html><body>百度安全验证 请完成验证" + ("x" * 1200) + "</body></html>"
        query = _SearchHarness(html)

        result = query.search_company("北京目标科技有限公司", max_retries=1)

        self.assertIsNone(result)
        self.assertEqual(len(query.opened_browser_calls), 1)
        self.assertEqual(query.opened_browser_calls[0][1], "aiqicha_search_drissionpage")


if __name__ == "__main__":
    unittest.main()
