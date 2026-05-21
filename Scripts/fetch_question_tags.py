import argparse
import ast
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

SITE_CONFIG = {
    "cn": {
        "base_url": "https://leetcode.cn",
        "default_question_urls": "Que/question_urls.json",
        "default_cookies_file": "Cookies.txt",
        "default_output": "Que/question_tags.json",
        "session_cookie_candidates": ["LEETCODE_SESSION", "LEETCODE_SESSION_US"],
    },
    "com": {
        "base_url": "https://leetcode.com",
        "default_question_urls": "Que/gquestion_urls.json",
        "default_cookies_file": "Gcookies.txt",
        "default_output": "Que/gquestion_tags.json",
        "session_cookie_candidates": ["LEETCODE_SESSION", "LEETCODE_SESSION_US"],
    },
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def resolve_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def normalize_cookies_for_site(raw_cookies: dict[str, Any], site: str) -> dict[str, Any]:
    cookies = dict(raw_cookies)
    session_cookie_name = None
    for candidate in SITE_CONFIG[site]["session_cookie_candidates"]:
        if candidate in cookies and cookies[candidate]:
            session_cookie_name = candidate
            break
    if session_cookie_name and session_cookie_name != "LEETCODE_SESSION":
        cookies["LEETCODE_SESSION"] = cookies[session_cookie_name]
    return cookies


def parse_qids(qids_text: str | None) -> set[str] | None:
    if not qids_text:
        return None
    parsed: set[str] = set()
    for item in qids_text.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise ValueError(f"Invalid qid: {item}")
        parsed.add(str(int(item)))
    return parsed


def load_question_urls(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"question_urls must be a JSON object: {path}")
    normalized: dict[str, str] = {}
    for key, value in data.items():
        if str(key).isdigit() and isinstance(value, str) and value.strip():
            normalized[str(int(str(key)))] = value.strip()
    return normalized


def select_question_ids(
    question_urls: dict[str, str],
    start_qid: int | None,
    end_qid: int | None,
    selected_qids: set[str] | None,
) -> list[str]:
    qids = []
    for qid in question_urls.keys():
        if not qid.isdigit():
            continue
        qid_int = int(qid)
        if start_qid is not None and qid_int < start_qid:
            continue
        if end_qid is not None and qid_int > end_qid:
            continue
        if selected_qids is not None and qid not in selected_qids:
            continue
        qids.append(qid)
    qids.sort(key=int)
    return qids


def extract_slug(problem_url: str) -> str:
    match = re.search(r"/problems/([^/?#]+)/?", problem_url)
    if not match:
        raise ValueError(f"Cannot extract slug from url: {problem_url}")
    return match.group(1)


def load_cookies_pool(cookie_file: Path, site: str) -> list[dict[str, Any]]:
    text = cookie_file.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(cookie_file))
    parsed_cookies: list[dict[str, Any]] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign) or not node.targets:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue

        var_name = target.id
        value: Any

        if var_name.startswith("COOKIES_"):
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(value, dict):
                parsed_cookies.append(value)

        if var_name == "COOKIES_LIST":
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        parsed_cookies.append(item)

    session_candidates = SITE_CONFIG[site]["session_cookie_candidates"]
    seen_sessions: set[str] = set()
    normalized_pool: list[dict[str, Any]] = []

    for raw_cookie in parsed_cookies:
        if not any(raw_cookie.get(name) for name in session_candidates):
            continue

        normalized = normalize_cookies_for_site(raw_cookie, site)
        session_value = str(normalized.get("LEETCODE_SESSION", "")).strip()
        if not session_value or session_value in seen_sessions:
            continue

        seen_sessions.add(session_value)
        normalized_pool.append(normalized)

    return normalized_pool


def build_session(base_url: str, cookies: dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": f"{base_url}/",
            "Origin": base_url,
            "Content-Type": "application/json",
        }
    )
    csrftoken = cookies.get("csrftoken")
    if csrftoken:
        session.headers["x-csrftoken"] = csrftoken
    return session


def graphql_post(
    session: requests.Session,
    base_url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> requests.Response:
    return session.post(f"{base_url}/graphql", json=payload, timeout=timeout_seconds)


def check_session(session: requests.Session, base_url: str, timeout_seconds: float) -> tuple[bool, str]:
    payload = {
        "operationName": "globalData",
        "variables": {},
        "query": "query globalData { userStatus { username isSignedIn } }",
    }

    try:
        resp = graphql_post(session, base_url, payload, timeout_seconds)
    except requests.RequestException as exc:
        return False, f"request_error: {exc}"

    if resp.status_code != 200:
        return False, f"http_{resp.status_code}"

    try:
        data = resp.json()
    except ValueError:
        return False, "invalid_json"

    if data.get("errors"):
        return False, f"graphql_errors: {data['errors'][0].get('message', 'unknown')}"

    user_status = data.get("data", {}).get("userStatus", {})
    if user_status.get("isSignedIn"):
        return True, str(user_status.get("username", "unknown"))
    return False, "not_signed_in"


def fetch_question_with_tags(
    session: requests.Session,
    base_url: str,
    slug: str,
    timeout_seconds: float,
) -> tuple[bool, dict[str, Any] | None, str]:
    payload = {
        "operationName": "questionData",
        "variables": {"titleSlug": slug},
        "query": (
            "query questionData($titleSlug: String!) {"
            " question(titleSlug: $titleSlug) {"
            " questionFrontendId"
            " title"
            " translatedTitle"
            " titleSlug"
            " difficulty"
            " topicTags { name slug translatedName }"
            " }"
            " }"
        ),
    }

    try:
        resp = graphql_post(session, base_url, payload, timeout_seconds)
    except requests.RequestException as exc:
        return False, None, f"request_error: {exc}"

    if resp.status_code == 429:
        return False, None, "rate_limited"
    if resp.status_code >= 500:
        return False, None, f"server_error_{resp.status_code}"
    if resp.status_code != 200:
        return False, None, f"http_{resp.status_code}"

    try:
        data = resp.json()
    except ValueError:
        return False, None, "invalid_json"

    errors = data.get("errors") or []
    if errors:
        message = errors[0].get("message", "graphql_error")
        return False, None, f"graphql_error: {message}"

    question = data.get("data", {}).get("question")
    if not question:
        return False, None, "question_not_found"

    return True, question, "ok"


def build_compact_entry(qid: str, difficulty: Any, tags: Any) -> dict[str, Any]:
    tag_names = []
    for tag in tags or []:
        if not isinstance(tag, dict):
            continue
        tag_name = tag.get("translatedName") or tag.get("name")
        if isinstance(tag_name, str) and tag_name.strip():
            tag_names.append(tag_name.strip())
    return {
        "qid": qid,
        "difficulty": difficulty,
        "tags": tag_names,
    }


def fetch_bulk_question_map(
    session: requests.Session,
    base_url: str,
    timeout_seconds: float,
    page_size: int = 200,
) -> tuple[dict[str, dict[str, Any]], str]:
    query = (
        "query problemsetQuestionList($categorySlug: String, $skip: Int, $limit: Int, $filters: QuestionListFilterInput) {"
        " problemsetQuestionList: questionList(categorySlug: $categorySlug, skip: $skip, limit: $limit, filters: $filters) {"
        " total: totalNum"
        " questions: data {"
        " questionFrontendId"
        " difficulty"
        " topicTags { name slug translatedName }"
        " }"
        " }"
        " }"
    )

    category_candidates = ["all-code-essentials", ""]

    for category_slug in category_candidates:
        question_map: dict[str, dict[str, Any]] = {}
        skip = 0
        total = None

        while True:
            payload = {
                "operationName": "problemsetQuestionList",
                "variables": {
                    "categorySlug": category_slug,
                    "skip": skip,
                    "limit": page_size,
                    "filters": {},
                },
                "query": query,
            }

            try:
                resp = graphql_post(session, base_url, payload, timeout_seconds)
            except requests.RequestException as exc:
                return {}, f"request_error: {exc}"

            if resp.status_code != 200:
                return {}, f"http_{resp.status_code}"

            try:
                data = resp.json()
            except ValueError:
                return {}, "invalid_json"

            errors = data.get("errors") or []
            if errors:
                # Try next category slug when current one is unsupported.
                question_map = {}
                break

            problemset = data.get("data", {}).get("problemsetQuestionList") or {}
            if total is None:
                total = int(problemset.get("total") or 0)

            questions = problemset.get("questions") or []
            if not questions:
                break

            for item in questions:
                if not isinstance(item, dict):
                    continue
                qid = str(item.get("questionFrontendId") or "").strip()
                if not qid.isdigit():
                    continue
                question_map[qid] = {
                    "difficulty": item.get("difficulty"),
                    "topicTags": item.get("topicTags") or [],
                }

            skip += len(questions)
            if total is not None and skip >= total:
                break

        if question_map:
            return question_map, "ok"

    return {}, "bulk_query_unavailable"


def main() -> None:
    script_dir = Path(__file__).resolve().parent

    env_site = os.getenv("LEETCODE_SITE", "com").lower()
    default_site = env_site if env_site in SITE_CONFIG else "com"

    parser = argparse.ArgumentParser(
        description="Fetch LeetCode question tags by qid with authenticated accounts"
    )
    parser.add_argument("--site", choices=["cn", "com"], default=default_site)
    parser.add_argument("--question-urls", default=None, help="Path to question_urls JSON")
    parser.add_argument("--cookies-file", default=None, help="Path to cookie definitions file")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--start-qid", type=int, default=None)
    parser.add_argument("--end-qid", type=int, default=None)
    parser.add_argument("--qids", default=None, help="Comma separated qids, e.g. 1,2,3")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between questions")
    parser.add_argument(
        "--mode",
        choices=["bulk", "per-question"],
        default="bulk",
        help="bulk=优先题库分页批量抓取，per-question=逐题抓取",
    )
    args = parser.parse_args()

    site = args.site
    site_cfg = SITE_CONFIG[site]
    base_url = site_cfg["base_url"]

    question_urls_path = resolve_path(
        args.question_urls or site_cfg["default_question_urls"],
        script_dir,
    )
    cookies_path = resolve_path(
        args.cookies_file or site_cfg["default_cookies_file"],
        script_dir,
    )
    output_path = resolve_path(
        args.output or site_cfg["default_output"],
        script_dir,
    )

    if not question_urls_path.exists():
        raise FileNotFoundError(f"question_urls file not found: {question_urls_path}")
    if not cookies_path.exists():
        raise FileNotFoundError(f"cookies file not found: {cookies_path}")

    question_urls = load_question_urls(question_urls_path)
    selected_qids = parse_qids(args.qids)
    target_qids = select_question_ids(question_urls, args.start_qid, args.end_qid, selected_qids)

    if not target_qids:
        raise ValueError("No question ids selected under current filters")

    cookies_pool = load_cookies_pool(cookies_path, site)
    if not cookies_pool:
        raise ValueError(f"No usable cookies found in: {cookies_path}")

    valid_accounts: list[dict[str, Any]] = []
    for idx, cookies in enumerate(cookies_pool, start=1):
        session = build_session(base_url, cookies)
        ok, detail = check_session(session, base_url, args.timeout)
        if ok:
            valid_accounts.append({"index": idx, "username": detail, "session": session})
            print(f"[auth] account#{idx} ok, username={detail}")
        else:
            print(f"[auth] account#{idx} invalid, reason={detail}")

    if not valid_accounts:
        raise RuntimeError("No valid authenticated account is available")

    print(
        f"[start] site={site}, total_qids={len(target_qids)}, valid_accounts={len(valid_accounts)}"
    )

    result_questions: list[dict[str, Any]] = []
    failed_questions: dict[str, str] = {}

    bulk_question_map: dict[str, dict[str, Any]] = {}
    if args.mode == "bulk":
        bulk_question_map, bulk_status = fetch_bulk_question_map(
            valid_accounts[0]["session"],
            base_url,
            args.timeout,
            page_size=200,
        )
        print(f"[bulk] status={bulk_status}, fetched={len(bulk_question_map)}")

    for idx, qid in enumerate(target_qids):
        if qid in bulk_question_map:
            item = bulk_question_map[qid]
            result_questions.append(
                build_compact_entry(qid, item.get("difficulty"), item.get("topicTags") or [])
            )
            if (idx + 1) % 50 == 0 or idx + 1 == len(target_qids):
                print(
                    f"[progress] {idx + 1}/{len(target_qids)} done, "
                    f"success={len(result_questions)}, failed={len(failed_questions)}"
                )
            if args.sleep > 0:
                time.sleep(args.sleep)
            continue

        problem_url = question_urls.get(qid, "")
        if not problem_url:
            failed_questions[qid] = "missing_question_url"
            continue

        try:
            slug = extract_slug(problem_url)
        except ValueError as exc:
            failed_questions[qid] = str(exc)
            continue

        success = False
        last_error = "unknown"

        for offset in range(len(valid_accounts)):
            account = valid_accounts[(idx + offset) % len(valid_accounts)]
            ok, question, status = fetch_question_with_tags(
                account["session"],
                base_url,
                slug,
                args.timeout,
            )

            if ok and question is not None:
                result_questions.append(
                    build_compact_entry(qid, question.get("difficulty"), question.get("topicTags") or [])
                )
                success = True
                break

            last_error = status
            if status == "rate_limited":
                time.sleep(max(1.0, args.sleep))

        if not success:
            failed_questions[qid] = last_error

        if (idx + 1) % 50 == 0 or idx + 1 == len(target_qids):
            print(
                f"[progress] {idx + 1}/{len(target_qids)} done, "
                f"success={len(result_questions)}, failed={len(failed_questions)}"
            )

        if args.sleep > 0:
            time.sleep(args.sleep)

    result_questions.sort(key=lambda x: int(x["qid"]))

    output_data = result_questions

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[done] wrote output: {output_path}")
    print(
        f"[summary] selected={len(target_qids)}, success={len(result_questions)}, failed={len(failed_questions)}"
    )


if __name__ == "__main__":
    main()
