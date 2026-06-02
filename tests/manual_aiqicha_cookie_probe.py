import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.Information_Gathering.Enterprise_Query.aiqicha_query import AiqichaQuery


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg]
    allow_browser = "--allow-browser" in args
    args = [arg for arg in args if arg != "--allow-browser"]
    company = args[0] if args else "中基宁波集团有限公司"
    query = AiqichaQuery()
    open_calls = []
    original_filter = query._filter_search_result_by_company_name
    original_open = query._open_with_drissionpage

    def fake_open(url, prefix, cookie_str=None, **kwargs):
        _ = cookie_str
        open_calls.append((url, prefix, kwargs))
        print(
            f"WOULD_OPEN_BROWSER prefix={prefix} "
            f"silent={bool(kwargs.get('silent_if_no_verify'))} url={url[:160]}"
        )
        return None

    def recording_open(url, prefix, cookie_str=None, **kwargs):
        open_calls.append((url, prefix, kwargs))
        print(
            f"OPENING_BROWSER prefix={prefix} "
            f"silent={bool(kwargs.get('silent_if_no_verify'))} url={url[:160]}"
        )
        return original_open(url, prefix, cookie_str, **kwargs)

    def logging_filter(data, target_name):
        if isinstance(data, dict):
            items = ((data.get("result") or {}).get("resultList") or [])
            if items:
                print("FILTER_TARGET", target_name)
                for index, item in enumerate(items, 1):
                    if not isinstance(item, dict):
                        continue
                    name = (
                        query._get_result_company_name(item)
                        or item.get("entName")
                        or item.get("titleName")
                        or item.get("name")
                        or ""
                    )
                    print(f"CANDIDATE_{index}", name, "PID", item.get("pid", ""))
        return original_filter(data, target_name)

    query._open_with_drissionpage = recording_open if allow_browser else fake_open
    query._filter_search_result_by_company_name = logging_filter
    result = query.search_company(company, max_retries=3)

    print("SEARCH_SUCCESS", bool(result))
    if result and isinstance(result, dict):
        items = ((result.get("result") or {}).get("resultList") or [])
        print("RESULT_COUNT", len(items))
        if items:
            item = items[0]
            name = (
                query._get_result_company_name(item)
                or item.get("entName")
                or item.get("titleName")
                or ""
            )
            print("MATCHED_NAME", name)
            print("PID", item.get("pid", ""))
            print("LEGAL_PERSON", item.get("legalPerson", ""))
            print("REG_NO", item.get("regNo", ""))
            print("TELEPHONE", item.get("telephone", ""))

    print("BROWSER_CALLS", len(open_calls))
    for index, (url, prefix, kwargs) in enumerate(open_calls, 1):
        print(
            f"BROWSER_CALL_{index} {prefix} "
            f"silent={bool(kwargs.get('silent_if_no_verify'))} {url[:160]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
