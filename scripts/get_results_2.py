import os
import requests
import json
import re
import logging

model_dict = {"qwen3_coder": "qwen3-coder-480b-a35b-instruct",
              "qwen3_235b": "qwen3-235b-a22b-thinking-2507",
              "gpt_oss": "gpt-oss-120b",
              "ds_32": "deepseek-v3.2",
              "ds_32t": "deepseek-v3.2-think",
              "llama4": "llama-4-maverick-17b-128e-instruct"
              }
model_list = ["ds_32"]


def load_txt(file_path):
    """
    读取sorted_problem_ids.txt文件，将题目id存入字符串列表

    参数:
        file_path: 文本文件路径

    返回:
        题目id字符串列表（空列表表示读取失败或文件为空）
    """
    problem_ids = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 读取所有行，去除换行符和首尾空白，过滤空行
            for line in f:
                pid = line.strip()
                if pid:  # 跳过空行
                    problem_ids.append(pid)
        print(f"成功读取 {len(problem_ids)} 个题目id")
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
    except Exception as e:
        print(f"读取文件失败：{e}")
    return problem_ids


def save_txt(path: str, codestr: str) -> bool:
    try:
        # 获取目录路径并创建（如果不存在）
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(codestr)
        logging.info(f"Code生成数据已成功保存至：{path}")
        return True
    except Exception as e:
        print(f"写入文件失败: {e}")
        return False


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


# prompt的模板
# prompt_template = """Task Description:
# - You need to implement the specified functionality within the given function/class interface.
# - Programming Language: {language}.
# - Functionality: {requirements}.
# - The interface must not be modified, and the input/output types must remain consistent.
# - Only provide the implementation of the function body/class methods. Do not include main(), test cases, comments, or any explanations.
#
# Function/Class Interface:
# {interface}
# """


prompt_template = """
Task Description:
- You must only implement the function body/class methods according to the given interface.
- Programming Language: {language}.
- Functionality: {requirements}.
- Strictly follow the interface: do not modify the interface, keep input/output types unchanged.
- **Critical Requirement:** Output ONLY the code of the function body/class methods. 
  - No explanations, no analysis, no comments (including inline comments).
  - No text like "Explanation", "Analysis", "Thinking", or any similar headings/descriptions.
  - No test cases, main() function, or any code outside the required function/class methods.
  - No additional text before, between, or after the code.

Function/Class Interface:
{interface}
"""

def solve_questions(problems_set, model_list, k=5):
    for problem_id in problems_set:
        print("*" * 100)
        problem_id = str(problem_id)
        if problem_id in problems_set:
            problem_sub_path = os.path.join(problems_path, problem_id)

            problem_txt = [
                f for f in os.listdir(problem_sub_path)
                if f.endswith(".txt") and (("English" in f) or ("english" in f))
            ]
            if len(problem_txt) == 0:  # 无效题目跳过
                continue
            problem_txt = problem_txt[0]
            # print(problem_txt)
            problem_full_path = os.path.join(problem_sub_path, problem_txt)

            with open(problem_full_path, "r", encoding="utf-8") as f:
                problem = f.read()

            # print("problem:\n", problem)
            if "图片URL" in problem:  # 带图片的题目跳过
                continue

            print("题目ID:", problem_id)
            language_list = ['C','C++','C#','Java','JavaScript','Python3','Rust','Golang']
            for language in language_list:
                # 读取给定函数/类格式
                Snippet_path = "./Snippets/{}/{}.json".format(problem_id, language)
                with open(Snippet_path, "r", encoding="utf-8") as f:
                    func = json.load(f)

                print("Given a function or class format as follows: \n", func)

                final_prompt = prompt_template.format(
                    language=language,
                    requirements=problem,
                    interface=func
                )
                # Generate k solutions for Que
                for ans_num in range(1, k+1):
                    for model in model_list:
                        SAVE_PATH = f"./GenCode/{model}/{problem_id}/{problem_id}_{language}_ans{ans_num}.txt"
                        if not os.path.isfile(SAVE_PATH):
                            print(f"[INFO] 请求题目 {problem_id}, model={model}, version={ans_num}")
                            solution = getResults(final_prompt, model)
                            print("{} language solution  (version {}) as follows: \n".format(language, ans_num))

                            # 清除非代码内容
                            solution_cleaned = re.sub(r"```[a-zA-Z0-9]*\n?", "", solution)
                            print(solution_cleaned)
                            save_txt(SAVE_PATH, solution_cleaned)
                        else:
                            print(f"{SAVE_PATH} is already exists.")
                        print(f"The No.{problem_id} Que solutions by model {model} version-{ans_num}  has finished.")



def getResults(prompt, model, retry=10):
    url = "https://api.linyinet.asia/v1/chat/completions"

    payload = json.dumps({
        "model": model_dict[model],
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }, ensure_ascii=False)

    headers = {
        'Content-Type': 'application/json',
        'appid': '',
        'Authorization': f'Bearer {API_KEY}'
    }

    for i in range(retry):

        try:
            response = requests.post(
                url,
                headers=headers,
                data=payload.encode("utf-8"),
                timeout=(10, 60)   # ⭐ 就加在这里
            )
            response.raise_for_status()

            result = response.json()
            return result['choices'][0]['message']['content']

        except requests.exceptions.Timeout:
            print(f"[TIMEOUT] 第 {i+1} 次请求超时，重试中...")
        except Exception as e:
            print(f"[ERROR] 第 {i+1} 次请求失败：{e}")

    raise RuntimeError("API 多次超时/失败，已放弃该请求")



if __name__ == '__main__':
    start_id = 144
    end_id = 1000
    problems_path = "description/merged"
    que_ids_path = "./final_que_ids.txt"
    que_des_ids = load_txt(que_ids_path)
    que_des_id_list = que_des_ids[start_id:end_id]

    solve_questions(que_des_id_list, model_list)
    # print(f"The No.{start_id}~{end_id} Que solutions by model {model} has finished.")
