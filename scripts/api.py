import os
import requests
import json
import re
import logging
import time

# 配置日志（打印运行信息，方便排查）
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

# 直接使用模型全名
model_list = ["claude-3-5-haiku-20241022"]  # 本次使用的模型列表

# -------------------------- 核心配置（自动推导路径）--------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)  # 根目录：rawdata
# 正确题解读取目录：根目录/Leetcode_Correct_Solutions（先前生成的正确题解目录）
CORRECT_SOLUTION_ROOT = os.path.join(ROOT_DIR, "Code")
# 其他固定目录（均基于根目录CodeGen）
SNIPPETS_DIR = os.path.join(ROOT_DIR, "Snippets")    # 接口文件目录
TRANSCODE_ROOT = os.path.join(ROOT_DIR, "TransCode")  # 翻译结果保存目录
# ------------------------------------------------------------------------------------------

# 全局缓存：已查找的<题目ID-语言>对应正确题解路径（避免重复遍历目录，提升效率）
correct_sol_cache = {}

def load_pair(file_path):
    """读取语言转换对文件（路径基于根目录CodeGen）"""
    lang_pairs = []
    abs_file_path = os.path.join(ROOT_DIR, file_path)
    try:
        with open(abs_file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r'\s+', line)
                if len(parts) != 2:
                    print(f"⚠️  第{line_num}行格式错误，需2个空格分隔的语言名称，跳过")
                    continue
                lang1, lang2 = parts
                lang_pairs.append([lang1, lang2])
        print(f"✅ 成功读取 {len(lang_pairs)} 个语言转换对（文件：{abs_file_path}）")
    except FileNotFoundError:
        print(f"❌ 错误：语言对文件不存在 -> {abs_file_path}")
    except Exception as e:
        print(f"❌ 读取语言对文件失败：{str(e)}")
    return lang_pairs

def load_txt(file_path):
    """读取题目ID文件（路径基于根目录CodeGen）"""
    content_list = []
    abs_file_path = os.path.join(ROOT_DIR, file_path)
    try:
        with open(abs_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                content = line.strip()
                if content:
                    content_list.append(content)
        print(f"✅ 成功读取 {len(content_list)} 条题目ID（文件：{abs_file_path}）")
    except FileNotFoundError:
        print(f"❌ 错误：题目ID文件不存在 -> {abs_file_path}")
    except Exception as e:
        print(f"❌ 读取题目ID文件失败：{str(e)}")
    return content_list

def save_txt(path: str, codestr: str) -> bool:
    """保存翻译结果（路径自动基于TransCode根目录，自动创建多级目录）"""
    abs_path = os.path.join(TRANSCODE_ROOT, path)
    try:
        dir_path = os.path.dirname(abs_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(codestr)
        logging.info(f"✅ 翻译结果已保存：{abs_path}")
        return True
    except Exception as e:
        logging.error(f"❌ 写入文件失败 {abs_path}：{str(e)}")
        return False

def save_json(data, file_path: str, encoding: str = "utf-8", indent: int = 4, ensure_ascii: bool = False) -> bool:
    """保存JSON（保留原函数，路径基于根目录CodeGen）"""
    abs_file_path = os.path.join(ROOT_DIR, file_path)
    try:
        dir_path = os.path.dirname(abs_file_path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            logging.info(f"📁 自动创建目录：{dir_path}")
        with open(abs_file_path, "w", encoding=encoding) as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
        logging.info(f"✅ JSON已保存：{abs_file_path}")
        return True
    except Exception as e:
        logging.error(f"❌ 写入JSON失败：{str(e)}")
        return False

# 代码转换提示词模板（保留原逻辑，确保翻译一致性）
prompt_template = """Task Description:
- You need to translate the given source programming language program code into the corresponding target programming language according to the given function/class interface, and ensure that the functionality is consistent with the source programming language code.
- Source programming language: {language_s}
- Target programming language: {language_t}
- Source programming code: {code_s}
- The interface must not be modified, and the input/output types must remain consistent.
- Only the function body/class method implementation should be provided. Do not include main(), test cases, comments, or any explanation.
- **Critical Requirement:** Output ONLY the code of the function body/class methods. 
  - No explanations, no analysis, no comments (including inline comments).
  - No text like "Explanation", "Analysis", "Thinking", or any similar headings/descriptions.
  - No test cases, main() function, or any code outside the required function/class methods.
  - No additional text before, between, or after the code.
Function/class interface:
{interface}
"""


def _extract_error_message(response: requests.Response) -> str:
    try:
        data = response.json()
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "")
        if isinstance(error, str):
            return error
    except Exception:
        pass
    return (response.text or "").strip()


def _is_group_unavailable(message: str) -> bool:
    text = (message or "").lower()
    keywords = ("分组", "下无", "无可用", "渠道", "unavailable", "group")
    return any(k in text for k in keywords)

def getResults(prompt, model_name):
    """调用API获取翻译结果；对临时故障重试，对分组不可用错误直接跳过。"""
    url = "https://api.linyinet.asia/v1/chat/completions"
    payload = json.dumps({
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }, ensure_ascii=False)
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    }
    retry_statuses = {429, 500, 502, 503, 504}
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                url,
                headers=headers,
                data=payload.encode("utf-8"),
                timeout=30
            )
        except requests.exceptions.Timeout:
            if attempt < max_attempts:
                wait_seconds = 2 * attempt
                logging.warning(
                    f"⚠️ API请求超时（模型={model_name}，第{attempt}/{max_attempts}次），{wait_seconds}s后重试"
                )
                time.sleep(wait_seconds)
                continue
            logging.error(f"❌ API请求超时（30秒），模型：{model_name}，已放弃")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ API调用失败：{str(e)}，模型：{model_name}")
            return None

        if response.status_code == 200:
            try:
                res_json = response.json()
                solution = res_json['choices'][0]['message']['content'].strip()
                logging.info(f"✅ 模型{model_name}调用成功，获取翻译结果")
                return solution
            except json.JSONDecodeError:
                logging.error(f"❌ API响应不是有效JSON，模型：{model_name}，响应内容：{response.text[:500]}")
                return None
            except KeyError as e:
                logging.error(f"❌ API响应格式错误，缺失字段：{e}，模型：{model_name}，响应内容：{response.text[:500]}")
                return None

        error_message = _extract_error_message(response)
        if response.status_code == 503 and _is_group_unavailable(error_message):
            logging.warning(
                f"⚠️ 模型{model_name}分组/渠道不可用（HTTP 503），跳过。信息：{error_message[:200]}"
            )
            return None

        if response.status_code in retry_statuses and attempt < max_attempts:
            wait_seconds = 2 * attempt
            logging.warning(
                f"⚠️ API请求HTTP错误：{response.status_code}（模型={model_name}，第{attempt}/{max_attempts}次），"
                f"{wait_seconds}s后重试，响应：{error_message[:200]}"
            )
            time.sleep(wait_seconds)
            continue

        logging.error(
            f"❌ API请求HTTP错误：{response.status_code}，模型：{model_name}，响应内容：{error_message[:500]}"
        )
        return None

    return None

def find_first_correct_solution(problem_id, language_s):
    """
    核心函数：查找指定题目+语言的第一个正确题解
    兼容两种目录结构：
    1) Code/题目ID/语言/题解文件
    2) Code/题目ID/题目ID_语言_ansN.txt
    """
    global correct_sol_cache
    problem_id = str(problem_id).strip()
    language_raw = language_s.strip()
    language_lower = language_raw.lower()
    cache_key = f"{problem_id}_{language_lower}"

    # 1. 先查缓存，已查找过直接返回，提升效率
    if cache_key in correct_sol_cache:
        return correct_sol_cache[cache_key]

    try:
        # 2. 优先兼容当前结构：Code/题目ID/题目ID_语言_ansN.txt
        problem_dir = os.path.join(CORRECT_SOLUTION_ROOT, problem_id)
        if os.path.isdir(problem_dir):
            filename_pattern = re.compile(
                rf"^{re.escape(problem_id)}_{re.escape(language_raw)}_ans(\d+)\.txt$",
                re.IGNORECASE,
            )
            matched_files = []
            for filename in os.listdir(problem_dir):
                full_path = os.path.join(problem_dir, filename)
                if not os.path.isfile(full_path):
                    continue
                match = filename_pattern.match(filename)
                if match:
                    matched_files.append((int(match.group(1)), filename))

            if matched_files:
                matched_files.sort(key=lambda item: item[0])
                first_sol_file = matched_files[0][1]
                abs_sol_path = os.path.join(problem_dir, first_sol_file)
                with open(abs_sol_path, 'r', encoding='utf-8') as f:
                    if f.read().strip():
                        logging.info(f"✅ 找到{problem_id}-{language_raw}第一个正确题解：{first_sol_file}")
                        correct_sol_cache[cache_key] = (abs_sol_path, first_sol_file)
                        return abs_sol_path, first_sol_file

        # 3. 兼容旧结构：Code/题目ID/语言/题解文件
        lang_dir = os.path.join(problem_dir, language_lower)
        if os.path.isdir(lang_dir):
            sol_files = sorted(
                [f for f in os.listdir(lang_dir) if os.path.isfile(os.path.join(lang_dir, f))],
                key=lambda x: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', x)]
            )
            for first_sol_file in sol_files:
                abs_sol_path = os.path.join(lang_dir, first_sol_file)
                with open(abs_sol_path, 'r', encoding='utf-8') as f:
                    if f.read().strip():
                        logging.info(f"✅ 找到{problem_id}-{language_raw}第一个正确题解：{first_sol_file}")
                        correct_sol_cache[cache_key] = (abs_sol_path, first_sol_file)
                        return abs_sol_path, first_sol_file

        logging.warning(f"⚠️  未找到正确题解：题目{problem_id} 语言{language_raw}，跳过该语言对")
        correct_sol_cache[cache_key] = (None, None)
        return None, None
    except Exception as e:
        logging.error(f"❌ 遍历正确题解目录失败：{str(e)}")
        correct_sol_cache[cache_key] = (None, None)
        return None, None

def solve_questions(problems_set, lang_pairs, model_list, k=5):
    """主逻辑：遍历题目+语言对，翻译并保存结果（适配新目录结构）"""
    # 前置校验：空值直接返回
    if not problems_set or not lang_pairs or not model_list:
        print("⚠️  题目列表/语言对/模型列表为空，无需处理")
        return
    # 校验核心目录是否存在
    if not os.path.isdir(CORRECT_SOLUTION_ROOT):
        print(f"❌ 致命错误：正确题解根目录不存在 -> {CORRECT_SOLUTION_ROOT}")
        return
    if not os.path.isdir(SNIPPETS_DIR):
        print(f"❌ 致命错误：接口文件根目录不存在 -> {SNIPPETS_DIR}")
        return

    for problem_id in problems_set:
        print("\n" + "*" * 120)
        problem_id = str(problem_id).strip()
        print(f"📌 开始处理题目ID: {problem_id}")

        for language_s, language_t in lang_pairs:
            print(f"\n🔄 处理语言转换：{language_s} -> {language_t}")
            # 1. 查找第一个正确题解（核心：从Leetcode_Correct_Solutions读取）
            abs_sol_path, sol_filename = find_first_correct_solution(problem_id, language_s)
            if abs_sol_path is None:
                continue  # 未找到正确题解，跳过该语言对

            # 2. 读取正确题解代码（兼容txt/json等格式，直接读取内容）
            try:
                with open(abs_sol_path, 'r', encoding='utf-8') as f:
                    code_s = f.read().strip()
                if not code_s:
                    logging.warning(f"⚠️  正确题解文件内容为空：{abs_sol_path}，跳过")
                    continue
                print(f"📋 翻译源：{sol_filename}（路径：{abs_sol_path}）")
            except Exception as e:
                logging.error(f"❌ 读取正确题解失败：{str(e)}，跳过")
                continue

            # 3. 读取目标语言接口文件（Snippets/题目ID/语言.json）
            snippet_file = os.path.join(SNIPPETS_DIR, problem_id, f"{language_t}.json")
            if not os.path.isfile(snippet_file):
                logging.error(f"❌ 目标语言接口文件不存在 -> {snippet_file}，跳过")
                continue
            try:
                with open(snippet_file, "r", encoding="utf-8") as f:
                    func_interface = json.load(f)
                print(f"📋 目标语言{language_t}接口：\n{json.dumps(func_interface, indent=2, ensure_ascii=False)}")
            except json.JSONDecodeError:
                logging.error(f"❌ 接口文件JSON格式错误 -> {snippet_file}，跳过")
                continue
            except Exception as e:
                logging.error(f"❌ 读取接口文件失败：{str(e)}，跳过")
                continue

            # 4. 构造最终提示词
            final_prompt = prompt_template.format(
                language_s=language_s,
                language_t=language_t,
                code_s=code_s,
                interface=json.dumps(func_interface, indent=2, ensure_ascii=False)
            )

            # 5. 生成k个版本的翻译结果（保留原逻辑，幂等性校验）
            for ans_num in range(1, k + 1):
                for model in model_list:
                    # 构造保存路径：TransCode/模型名/题目ID/题目ID_源语言_目标语言_ansX.txt
                    save_path = f"{model}/{problem_id}/{problem_id}_{language_s}_{language_t}_ans{ans_num}.txt"
                    abs_save_path = os.path.join(TRANSCODE_ROOT, save_path)
                    # 幂等性校验：文件已存在则跳过，避免重复生成
                    if os.path.isfile(abs_save_path):
                        print(f"⏩ 文件已存在，跳过 -> {abs_save_path}")
                        continue

                    # 6. 调用模型翻译并保存
                    try:
                        # 调用API获取结果
                        solution = getResults(final_prompt, model)
                        if not solution:
                            logging.warning(f"⚠️ 模型{model}版本{ans_num}未返回有效结果，跳过")
                            continue
                        # 清理模型返回的非代码内容（移除```代码块标记）
                        solution_cleaned = re.sub(r"```[a-zA-Z0-9]*\n?", "", solution).strip()
                        solution_cleaned = re.sub(r"\n```$", "", solution_cleaned).strip()
                        # 打印部分结果（避免过长）
                        preview = solution_cleaned[:500] + "..." if len(solution_cleaned) > 500 else solution_cleaned
                        print(f"\n✅ {language_s}->{language_t} 版本{ans_num} 翻译结果预览：\n{preview}")
                        # 保存清理后的代码
                        if save_txt(save_path, solution_cleaned):
                            print(f"📥 已保存版本{ans_num} -> {abs_save_path}")
                    except Exception as e:
                        logging.error(f"❌ 模型{model}生成版本{ans_num}失败：{str(e)}，跳过")
                        continue
        print(f"\n✅ 题目{problem_id} 所有语言对处理完成")
    print("\n" + "*" * 120)
    print(f"🎉 所有指定题目处理完成！翻译结果保存至：{TRANSCODE_ROOT}")

# -------------------------- 主程序入口（仅需修改以下4个配置）--------------------------
if __name__ == '__main__':
    # 配置1：处理题目范围（索引从0开始，左闭右开，如0-10处理前10题）
    start_id = 1
    end_id = 4000
    # 配置2：语言转换对文件路径（默认rawdata/language_pairs.txt，可通过环境变量覆盖）
    translate_pair_path = os.environ.get('TRANSLATE_PAIR_PATH', 'language_pairs.txt')
    # 配置3：题目ID文件路径（默认rawdata/full_ids.txt，可通过环境变量覆盖）
    que_ids_path = os.environ.get('QUE_IDS_PATH', 'ids_top300.txt')

    # 加载数据
    lang_pairs = load_pair(translate_pair_path)  # 加载语言转换对
    all_que_ids = load_txt(que_ids_path)         # 加载所有题目ID
    target_que_ids = all_que_ids[start_id:end_id]# 截取待处理题目ID

    # 执行主逻辑：生成翻译结果（k=5表示每个翻译任务生成5个版本）
    solve_questions(
        problems_set=target_que_ids,
        lang_pairs=lang_pairs,
        model_list=model_list,
        k=5
    )
