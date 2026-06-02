import json
import unittest
from unittest.mock import patch

from modules.Information_Gathering.Enterprise_Query.tianyancha_query import TianyanchaQuery


class _DummyResponse:
    def __init__(self, html: str):
        self.status_code = 200
        self.text = html

    def raise_for_status(self):
        return None


class _SearchHarness(TianyanchaQuery):
    def __init__(self, html: str):
        self.html = html
        self.browser_calls = []
        self.tianyancha_cookies = {}
        self.tianyancha_cookie_raw = ""
        self._verification_page_capture = None
        self._verification_page_ref = None
        self._pending_browser_close = None
        self._verification_user_closed = False
        self._verification_in_progress = False

    def _make_request(self, method, url, status_callback=None, **kwargs):
        return _DummyResponse(self.html)

    def _handle_captcha_verification(self, url, response_text=None, status_callback=None, **kwargs):
        self.browser_calls.append((url, response_text, kwargs))
        return False


def _next_data_html(company_list):
    data = {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "state": {
                                "data": {
                                    "data": {
                                        "companyList": company_list,
                                    }
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(data, ensure_ascii=False)}"
        "</script></head><body></body></html>"
    )


class TianyanchaQueryTest(unittest.TestCase):
    def test_plain_tianyancha_html_is_not_forced_visible_in_silent_mode(self):
        query = object.__new__(TianyanchaQuery)

        html = "<html><head><title>天眼查</title></head><body>正在加载企业数据</body></html>"

        self.assertFalse(query._html_requires_browser_verification(html))

    def test_captcha_html_still_requires_visible_browser(self):
        query = object.__new__(TianyanchaQuery)

        html = "<html><body>请完成安全验证 行为验证 验证码</body></html>"

        self.assertTrue(query._html_requires_browser_verification(html))

    def test_no_company_data_search_fallback_is_silent_first(self):
        query = _SearchHarness(_next_data_html([]))

        with patch("builtins.print"):
            result = query.search_company("北京目标科技有限公司")

        self.assertFalse(result["success"])
        self.assertEqual(len(query.browser_calls), 1)
        self.assertTrue(query.browser_calls[0][2].get("silent_if_no_verify"))


if __name__ == "__main__":
    unittest.main()
