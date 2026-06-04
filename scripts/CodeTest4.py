'''
CODE TEST (NON VIP)
V2
2025.09.30

'''
import os
import requests
import re
import random
import logging
import time
import json
from datetime import datetime
from typing import List, Dict, Optional
import argparse

FILEPATH = os.path.dirname(os.path.abspath(__file__)) + '/'
print(FILEPATH)

'''
lang dict
{Python3, C#, C++, C, JavaScript, Java, Golang, Rust}
python3, csharp, cpp, c, javascript, java, golang, rust
'''
LANGDICT = {
    "Python3": "python3",
    "C": "c",
    "C++": "cpp",
    "C#": "csharp",
    "JavaScript": "javascript",
    "Java": "java",
    "Golang": "golang",
    "Rust": "rust",
}


COOKIES_List = []
APP_CONFIG = {
    "lang_map": LANGDICT,
    "cookies_pool": COOKIES_List,
    "paths": {
        "question_urls": os.path.join(FILEPATH, "Que", "gquestion_urls.json"),
        "qid_mapping": os.path.join(FILEPATH, "Que", "Qid_mapping.json"),
        "code_base_root": os.path.join(FILEPATH, "GenCode"),
        "submit_base_root": os.path.join(FILEPATH, "Submit_Results"),
        "code_root": "",
        "submit_root": "",
    },
    "wait_seconds": {
        "between_languages": (15, 20),
        "between_questions": (0, 0),
        "after_submit": (10, 15),
    },
    "defaults": {
        "model_name": "qwen3-8b",
        "start_id": 1,
        "end_id": 1500,
        "batch_group_size": 5,
    },
    "runtime": {
        "request_timeout_seconds": 20,
        "request_retry_count": 1,
        "request_retry_backoff_seconds": 3,
        "status_poll_interval_seconds": 5,
        "status_poll_max_attempts": 24,
    }
}


def chunked(items: List[int], size: int) -> List[List[int]]:
    if size <= 0:
        size = 1
    return [items[i:i + size] for i in range(0, len(items), size)]


def parse_id_list(id_list_text: str) -> List[int]:
    if not id_list_text:
        return []
    raw_ids = [part.strip() for part in id_list_text.split(',') if part.strip()]
    parsed_ids = []
    for raw_id in raw_ids:
        if not raw_id.isdigit():
            raise ValueError(f"无效ID: {raw_id}，请使用逗号分隔的整数列表")
        parsed_ids.append(int(raw_id))
    return parsed_ids


def get_question_folders(
    root_dir: str,
    start_qid: int = None,
    end_qid: int = None,
    selected_qids: Optional[List[int]] = None
) -> List[str]:
    """
    获取根目录下指定区间内的题目编号子文件夹
    :param root_dir: 根目录路径
    :param start_qid: 起始题目编号（包含）
    :param end_qid: 终止题目编号（包含）
    :return: 符合条件的文件夹路径列表
    """
    if not os.path.exists(root_dir):
        raise FileNotFoundError(f"根目录不存在：{root_dir}")

    selected_set = set(selected_qids) if selected_qids else None

    # 筛选出所有数字命名的子文件夹（假设题目编号为数字）
    valid_folders = []
    for item in os.listdir(root_dir):
        item_path = os.path.join(root_dir, item)
        if os.path.isdir(item_path) and item.isdigit():
            qid = int(item)
            if selected_set is not None and qid not in selected_set:
                continue
            # 检查是否在指定区间内
            if (start_qid is None or qid >= start_qid) and (end_qid is None or qid <= end_qid):
                valid_folders.append(item_path)

    # 按题目编号升序排序
    valid_folders.sort(key=lambda x: int(os.path.basename(x)))
    return valid_folders


def parse_txt_filename(filename: str) -> Dict[str, str]:
    """解析TXT文件名，提取qid、lang和ans_idx"""
    # 匹配格式：{qid}_{lang}_ans{ans_idx}.txt
    pattern = r"^(\d+)_([\w+#]+)_ans(\d+)\.txt$"
    match = re.match(pattern, filename)

    if not match:
        return None

    return {
        "qid": match.group(1),
        "lang": match.group(2),
        "ans_idx": match.group(3)
    }


def test_exe(
    ROOT_DIR,
    question_urls,
    logger,
    qid_dict,
    start_qid: int = None,
    end_qid: int = None,
    selected_qids: Optional[List[int]] = None
):
    """
    修改后的测试执行函数，支持按题目区间筛选
    :param start_qid: 起始题目编号（包含）
    :param end_qid: 终止题目编号（包含）
    """
    try:
        # 获取指定区间内的题目子文件夹
        question_folders = get_question_folders(
            ROOT_DIR,
            start_qid=start_qid,
            end_qid=end_qid,
            selected_qids=selected_qids
        )
        if not question_folders:
            print(f"在区间 {start_qid}-{end_qid} 内未找到任何题目子文件夹")
            return

        print(f"共发现 {len(question_folders)} 个符合条件的题目文件夹，开始处理：\n")
        if selected_qids:
            print(f"测试Code题目列表：{selected_qids}\n")
        else:
            print(f"测试Code题目区间：{start_qid if start_qid else '最小'} - {end_qid if end_qid else '最大'}\n")

        # 创建测试代理列表
        test_agent_list = []
        for i in range(len(APP_CONFIG["cookies_pool"])):
            test_agent = Test(APP_CONFIG["cookies_pool"][i], qid_dict)
            test_agent_list.append(test_agent)
            print(f'创建测试代理 {i}')

        que_index = 0
        logging.info(f'#### 测试开始 ####')
        logging.info(f'处理题目区间：{start_qid if start_qid else "最小"} - {end_qid if end_qid else "最大"}')

        # 遍历每个题目文件夹
        for folder in question_folders:
            qid = os.path.basename(folder)
            problem_url = question_urls.get(qid)

            if not problem_url:
                print(f"警告：题目 {qid} 未找到对应的URL，跳过处理")
                continue

            logging.info(f'#### 开始处理题目 {qid} ####')
            print(f'\n===== 处理题目 {qid} =====')

            # 获取文件夹中所有TXT文件
            txt_files = []
            for file in os.listdir(folder):
                if file.lower().endswith(".txt"):
                    txt_files.append(file)

            # 按文件名排序（确保ans_idx顺序执行）
            txt_files.sort()

            # 处理每个TXT文件
            for txt_file in txt_files:
                # 解析文件名
                parsed = parse_txt_filename(txt_file)
                if not parsed:
                    print(f"跳过不符合格式的文件：{txt_file}")
                    continue

                # 验证解析结果与文件夹是否匹配
                if parsed["qid"] != qid:
                    print(f"文件名与文件夹不匹配：{txt_file} 在 {qid} 文件夹中")
                    continue

                lang = parsed["lang"]
                ans_idx = parsed["ans_idx"]
                file_path = os.path.join(folder, txt_file)

                # 检查对应的结果JSON文件是否已经存在
                result_dir = os.path.join(APP_CONFIG["paths"]["submit_root"], qid)
                # 获取语言在LANGDICT中的值
                if lang in APP_CONFIG["lang_map"]:
                    language_key = APP_CONFIG["lang_map"][lang]
                else:
                    print(f"不支持的语言 {lang}，跳过文件 {txt_file}")
                    continue

                result_file = f"{qid}_{language_key}_{ans_idx}.json"  # 注意：这里用language_key而不是lang
                result_path = os.path.join(result_dir, result_file)

                if os.path.exists(result_path):
                    print(f"结果文件已存在，跳过处理: {txt_file} -> {result_file}")
                    logging.info(f"结果文件已存在，跳过处理: {txt_file} -> {result_file}")
                    continue

                # 读取代码内容
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        typed_code = f.read()
                except Exception as e:
                    print(f"读取文件 {txt_file} 失败：{str(e)}")
                    continue

                # 检查语言是否支持
                if lang not in APP_CONFIG["lang_map"]:
                    print(f"不支持的语言 {lang}，跳过文件 {txt_file}")
                    continue

                language = APP_CONFIG["lang_map"][lang]
                agent_index = que_index % len(test_agent_list)
                que_index += 1

                print(f'处理 {lang} 答案 {ans_idx}（使用代理 {agent_index + 1}）')
                logging.info(f'#### 测试题目 {qid} {lang} 答案 {ans_idx}')

                # 提交测试
                try:
                    test_agent_list[agent_index].test_one_ans(
                        problem_url=problem_url,
                        language=language,
                        question_id=qid,
                        typed_code=typed_code,
                        ans_id=ans_idx
                    )
                except Exception as e:
                    logging.exception(f"处理失败，继续下一个文件: qid={qid}, file={txt_file}, error={str(e)}")
                    print(f"处理失败，继续下一个文件: {txt_file}, error={str(e)}")
                    time.sleep(2)
                    continue

                # 语言间等待
                wait_low, wait_high = APP_CONFIG["wait_seconds"]["between_languages"]
                wait_time = random.randint(wait_low, wait_high)
                print(f'======== 等待 {wait_time} 秒（语言间隔） =========')
                time.sleep(wait_time)

            # 题目间等待
            wait_low, wait_high = APP_CONFIG["wait_seconds"]["between_questions"]
            wait_time = random.randint(wait_low, wait_high)
            print(f'======== 等待 {wait_time} 秒（题目间隔） =========')
            time.sleep(wait_time)

    except Exception as e:
        print(f"处理过程出错：{str(e)}")
        logging.error(f"处理过程出错：{str(e)}")


def load_json(json_file):
    """
    从JSON文件中提取内容
    :param json_file: JSON文件路径
    """
    json_data = None
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            json_data = json.load(f)
    except FileNotFoundError:
        logging.info(f"错误：JSON文件 {json_file} 不存在！")
    except json.JSONDecodeError:
        logging.info(f"错误：JSON文件 {json_file} 格式错误，无法解析！")
    except Exception as e:
        logging.info(f"错误：读取JSON文件时发生异常 - {str(e)}")

    return json_data


def save_json(data, file_path: str, encoding: str = "utf-8", indent: int = 4, ensure_ascii: bool = False) -> bool:
    # 1. 提取文件所在的目录路径
    dir_path = os.path.dirname(file_path)

    # 2. 若目录不存在，则创建（包括多级目录）
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)  # exist_ok=True避免目录已存在时报错
        logging.info(f"已自动创建目录：{dir_path}")

    # 3. 写入JSON数据
    with open(file_path, "w", encoding=encoding) as f:
        json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)

    logging.info(f"JSON数据已成功保存至：{file_path}")


def get_sorted_json_files(dir_path: str) -> List[str]:
    """
    获取目录下所有JSON文件，并按文件名升序排序
    :param dir_path: 目标目录路径
    :return: 排序后的JSON文件完整路径列表
    """
    # 检查目录是否存在
    if not os.path.exists(dir_path):
        raise FileNotFoundError(f"目录不存在：{dir_path}")
    if not os.path.isdir(dir_path):
        raise NotADirectoryError(f"{dir_path} 不是一个目录")

    # 筛选出所有.json文件
    all_files = os.listdir(dir_path)
    json_files = [
        f for f in all_files
        if f.lower().endswith(".json") and os.path.isfile(os.path.join(dir_path, f))
    ]

    json_files.sort()

    # 返回完整路径
    return [os.path.join(dir_path, f) for f in json_files]

def set_logger(log_file: str):
    """配置日志，将info及以上级别日志保存到文件"""
    # 1. 获取logger实例
    logger = logging.getLogger("file_logger")
    logger.setLevel(logging.INFO)  # 只处理INFO及以上级别（DEBUG会被忽略）

    # 避免重复添加处理器（多次调用时防止日志重复）
    if logger.handlers:
        return logger

    # 2. 确保日志目录存在（如果log_file包含路径，如"logs/app.log"）
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # 3. 创建文件处理器（将日志写入文件）
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)  # 处理器也可单独设置级别（这里和logger一致）

    # 4. 定义日志格式（时间、级别、消息）
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)

    # 5. 给logger添加处理器
    logger.addHandler(file_handler)

    return logger


class Test():
    def __init__(self, cookies_id, qid_dict):
        # self.code = code
        # self.que_urls = que_urls
        # self.lang = lang
        # self.que_id = que_id
        # self.file_path = file_path
        self.cookies_id = cookies_id
        self.qid_dict = qid_dict
        self.base_url = "https://leetcode.com"

    def _request_once(self, session: requests.Session, method: str, url: str, **kwargs):
        timeout = APP_CONFIG["runtime"]["request_timeout_seconds"]
        retry_count = APP_CONFIG["runtime"]["request_retry_count"]
        retry_backoff = APP_CONFIG["runtime"]["request_retry_backoff_seconds"]

        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout

        for attempt in range(1, retry_count + 2):
            try:
                response = session.request(method=method, url=url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    logging.error(
                        f"请求失败: {method} {url} - 状态码: {response.status_code}，第{attempt}/{retry_count + 1}次"
                    )
                    print(f"请求失败: {method} {url} - 状态码: {response.status_code}，第{attempt}/{retry_count + 1}次")
                    if attempt <= retry_count:
                        time.sleep(retry_backoff)
                        continue
                    return None
                return response
            except (requests.RequestException, requests.Timeout) as exc:
                logging.error(f"请求失败并跳过: {method} {url} - {str(exc)}，第{attempt}/{retry_count + 1}次")
                print(f"请求失败并跳过: {method} {url} - {str(exc)}，第{attempt}/{retry_count + 1}次")
                if attempt <= retry_count:
                    time.sleep(retry_backoff)
                    continue
                return None

    def submit_code(self, problemUrl, lang, question_id, typed_code):
        # 创建会话以保持 cookies
        session = requests.Session()

        session.cookies.update(self.cookies_id)

        # 获取必要的cookies和CSRFtoken
        response = self._request_once(session, "GET", problemUrl)
        if response is None:
            return None

        domain_match = re.match(r"^https?://[^/]+", problemUrl)
        if domain_match:
            self.base_url = domain_match.group(0)

        csrftoken = session.cookies.get('csrftoken')
        if not csrftoken:
            csrftoken = response.cookies.get('csrftoken')
        if not csrftoken:
            # 如果 cookies 中没有，尝试从响应头中获取
            set_cookie = response.headers.get("set-cookie", "")
            pattern = re.compile(".*?csrftoken=(.*?);.*?", re.S)
            match = re.search(pattern, set_cookie)
            if match:
                csrftoken = match.group(1)

        if not csrftoken:
            print("无法获取 CSRF token")
            return None

        session.cookies.set('csrftoken', csrftoken)

        # 构建提交数据的 URL
        submit_url = problemUrl.replace("/description/", "/submit/")
        if "/submit/" not in problemUrl:
            submit_url = problemUrl + "/submit/"
        print(submit_url)
        # print(type(question_id))
        # print(question_id)
        # print(type(self.qid_dict[question_id]))
        # print(self.qid_dict[question_id])
        data = {
            "lang": lang,
            "question_id": self.qid_dict[question_id],
            "typed_code": typed_code
        }

        headers = {
            'x-csrftoken': csrftoken,
            'referer': problemUrl,
            'content-type': 'application/json',
            'origin': self.base_url,
            'x-requested-with': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0'
        }

        response = self._request_once(
            session,
            "POST",
            submit_url,
            data=json.dumps(data),
            headers=headers
        )
        if response is None:
            return None

        # 检查响应
        if response.status_code == 200:
            try:
                result = response.json()
                submission_id = result.get('submission_id')
                if submission_id is None:
                    submission_id = result.get('submissionId') or result.get('submissionID') or result.get('id')
                if submission_id is None:
                    logging.error(
                        f"提交响应缺少 submission_id，响应字段: {list(result.keys())}，响应内容: {response.text[:500]}"
                    )
                    print("提交响应缺少 submission_id，无法继续轮询")
                    print(f"响应内容: {response.text[:500]}")
                    return None

                result['submission_id'] = submission_id
                logging.info(f"提交成功，提交ID: {submission_id}")
                print(f"提交成功，提交ID: {submission_id}")
                return result
            except json.JSONDecodeError:
                logging.info("响应不是有效的JSON格式")
                print("响应不是有效的JSON格式")
                print(f"响应内容: {response.text}")
                return None
        else:
            logging.info(f"提交失败，状态码: {response.status_code}")
            print(f"提交失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return None

    def check_submission_status(self, submission_id):
        check_url = f"{self.base_url}/submissions/detail/{submission_id}/check/"
        session = requests.Session()
        session.cookies.update(self.cookies_id)
        response = self._request_once(
            session,
            "GET",
            check_url,
            headers={'referer': self.base_url + '/'}
        )
        if response is None:
            return None

        if response.status_code == 200:
            try:
                return response.json()
            except json.JSONDecodeError:
                logging.info("检查响应不是有效的JSON格式")
                print("检查响应不是有效的JSON格式")
                return None
        else:
            logging.info(f"检查提交状态失败，状态码: {response.status_code}")
            print(f"检查提交状态失败，状态码: {response.status_code}")
            return None

    def test_one_ans(self, problem_url, language, question_id, typed_code, ans_id):
        # 提交代码
        result = self.submit_code(problem_url, language, question_id, typed_code)
        status_dict = {}
        if result and 'submission_id' in result:
            submission_id = result['submission_id']

            logging.info(f"已提交代码，提交ID: {submission_id}")

            # 等待一段时间后检查提交状态
            wait_low, wait_high = APP_CONFIG["wait_seconds"]["after_submit"]
            time.sleep(random.randint(wait_low, wait_high))

            status = None
            poll_interval = APP_CONFIG["runtime"]["status_poll_interval_seconds"]
            max_attempts = APP_CONFIG["runtime"]["status_poll_max_attempts"]
            pending_states = {"PENDING", "STARTED"}

            for attempt in range(1, max_attempts + 1):
                status = self.check_submission_status(submission_id)
                if not status:
                    logging.warning(f"查询提交状态失败，submission_id={submission_id}，第{attempt}/{max_attempts}次")
                else:
                    state = status.get('state')
                    if state is None:
                        logging.warning(
                            f"状态轮询响应缺少 state 字段，submission_id={submission_id}，响应字段: {list(status.keys())}"
                        )
                        print(f"状态轮询响应缺少 state 字段，submission_id={submission_id}")
                        break
                    logging.info(f"状态轮询[{attempt}/{max_attempts}] submission_id={submission_id} state={state}")
                    print(f"状态轮询[{attempt}/{max_attempts}] submission_id={submission_id} state={state}")
                    if state == 'SUCCESS':
                        break
                    if state not in pending_states:
                        break

                if attempt < max_attempts:
                    time.sleep(poll_interval)

            status_dict['submit_id'] = submission_id
            if status:
                state = status.get('state')
                if state is None:
                    logging.warning(
                        f"提交状态响应缺少 state 字段，submission_id={submission_id}，响应字段: {list(status.keys())}"
                    )
                    print(f"提交状态响应缺少 state 字段，submission_id={submission_id}")
                    status_dict['state'] = 'UNKNOWN'
                    status_dict['error'] = 'missing_state_in_status_response'
                else:
                    logging.info(f"提交状态: {state}")
                    print(f"提交状态: {state}")
                    status_dict['state'] = state
                    if state == 'SUCCESS':
                        logging.info(f"运行结果: {status.get('status_msg')}")
                        logging.info(f"总测试样例: {status.get('total_testcases')}")
                        logging.info(f"通过样例数: {status.get('total_correct')}")
                        print(f"运行结果: {status.get('status_msg')}")
                        print(f"总测试样例: {status.get('total_testcases')}")
                        print(f"通过样例数: {status.get('total_correct')}")
                        status_dict['ac_status'] = status.get('status_msg')
                        status_dict['total_testcases'] = status.get('total_testcases')
                        status_dict['total_correct'] = status.get('total_correct')
                        if status.get('status_msg') == 'Accepted':
                            logging.info(f"运行时间: {status.get('status_runtime')}")
                            logging.info(f"运行时间超过: {status.get('runtime_percentile')}%的用户")
                            logging.info(f"内存使用: {status.get('status_memory')}")
                            logging.info(f"内存使用超过: {status.get('memory_percentile')}%的用户")
                            print(f"运行时间: {status.get('status_runtime')}")
                            print(f"运行时间超过: {status.get('runtime_percentile')}%的用户")
                            print(f"内存使用: {status.get('status_memory')}")
                            print(f"内存使用超过: {status.get('memory_percentile')}%的用户")
                            status_dict['runtime'] = status.get('status_runtime')
                            status_dict['runtime_percentile'] = status.get('runtime_percentile')
                            status_dict['memory'] = status.get('status_memory')
                            status_dict['memory_percentile'] = status.get('memory_percentile')
            else:
                status_dict['state'] = 'UNKNOWN'
                status_dict['error'] = 'status_query_failed_or_timeout'

        final_result_ready = (
            bool(result)
            and status_dict.get('submit_id')
            and status_dict.get('state') == 'SUCCESS'
            and bool(status_dict.get('ac_status'))
        )

        if final_result_ready:
            print(datetime.now().strftime("%Y%m%d-%H%M%S"))
            save_json(status_dict,
                      os.path.join(
                          APP_CONFIG["paths"]["submit_root"],
                          str(question_id),
                          f"{question_id}_{language}_{ans_id}.json"
                      ))
        elif result:
            logging.info(
                f"未获得最终判题结果，不落盘: question_id={question_id}, language={language}, ans_id={ans_id}, state={status_dict.get('state')}"
            )
            print(f"未获得最终判题结果，不落盘: qid={question_id}, lang={language}, ans={ans_id}, state={status_dict.get('state')}")




def main():
    parser = argparse.ArgumentParser(description="CODE TEST")
    parser.add_argument("-model_name", type=str, default="", help="模型名称（对应 GenCode 下子目录名），为空时使用 APP_CONFIG[defaults][model_name]")
    parser.add_argument("-start_id", type=int, default=APP_CONFIG["defaults"]["start_id"], help="起始ID（包含），仅处理该ID及以上的文件夹")
    parser.add_argument("-end_id", type=int, default=APP_CONFIG["defaults"]["end_id"], help="终止ID（包含），仅处理该ID及以下的文件夹")
    parser.add_argument("-id_list", type=str, default="", help="可选，逗号分隔题目ID列表，如：1,2,3,4,5")
    parser.add_argument("-batch_group_size", type=int, default=APP_CONFIG["defaults"]["batch_group_size"], help="批量ID分组大小，推荐5")
    args = parser.parse_args()

    model_name = args.model_name.strip() or APP_CONFIG["defaults"].get("model_name", "").strip()
    code_root_config = APP_CONFIG["paths"].get("code_root", "").strip()
    submit_root_config = APP_CONFIG["paths"].get("submit_root", "").strip()

    if code_root_config and submit_root_config:
        APP_CONFIG["paths"]["code_root"] = code_root_config
        APP_CONFIG["paths"]["submit_root"] = submit_root_config
        print("当前模式：使用 APP_CONFIG.paths.code_root / submit_root 直配目录")
    else:
        if not model_name:
            print("错误：请配置 model_name，或同时配置 code_root 和 submit_root")
            return
        APP_CONFIG["paths"]["code_root"] = os.path.join(APP_CONFIG["paths"]["code_base_root"], model_name)
        APP_CONFIG["paths"]["submit_root"] = os.path.join(
            APP_CONFIG["paths"]["submit_base_root"],
            f"Submit_Results_{model_name}"
        )
        print(f"当前模型：{model_name}")

    print(f"代码目录：{APP_CONFIG['paths']['code_root']}")
    print(f"结果目录：{APP_CONFIG['paths']['submit_root']}")

    question_urls = load_json(APP_CONFIG["paths"]["question_urls"])
    qid_dict = load_json(APP_CONFIG["paths"]["qid_mapping"])
    # 检查必要的配置文件是否加载成功，避免后续 NoneType 导致异常
    if not question_urls:
        print(f"错误：无法加载 {APP_CONFIG['paths']['question_urls']}，确认文件存在且为有效 JSON")
        return
    if not qid_dict:
        print(f"错误：无法加载 {APP_CONFIG['paths']['qid_mapping']}，确认文件存在且为有效 JSON")
        return
    # print(qid_dict)
    # 配置日志
    time_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = set_logger(log_file=os.path.join(FILEPATH, "logs", f"Code4Test_{time_stamp}.log"))

    # 题目根目录（包含多个题目编号子文件夹）
    # 根据仓库结构，数据位于 rawdata/GenCode/deepseek-v3.2
    ROOT_DIR = APP_CONFIG["paths"]["code_root"]

    try:
        id_list = parse_id_list(args.id_list)
    except ValueError as e:
        print(str(e))
        return

    group_size = max(1, min(args.batch_group_size, len(APP_CONFIG["cookies_pool"])))

    if id_list:
        id_groups = chunked(id_list, group_size)
        print(f"批量模式：共 {len(id_list)} 个ID，按 {group_size} 个一组，共 {len(id_groups)} 组")
        for index, id_group in enumerate(id_groups, start=1):
            print(f"\n===== 开始第 {index}/{len(id_groups)} 组：{id_group} =====")
            test_exe(
                ROOT_DIR,
                question_urls,
                logger,
                qid_dict,
                selected_qids=id_group
            )
    else:
        START_QID = args.start_id
        END_QID = args.end_id
        test_exe(ROOT_DIR, question_urls, logger, qid_dict, start_qid=START_QID, end_qid=END_QID)


if __name__ == "__main__":
    main()

