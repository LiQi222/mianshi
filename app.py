from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
import PyPDF2 as pdf
import os

# 初始化Flask应用，并指定静态文件夹
app = Flask(__name__, static_folder='static')
CORS(app) # 允许跨域请求

# --- 配置 DeepSeek API 密钥 ---
try:
    # 从环境变量中读取密钥
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未找到 DEEPSEEK_API_KEY 环境变量")
except Exception as e:
    print(f"API密钥配置错误: {e}")

# 新增的路由：用于提供网站主页
@app.route('/')
def serve_index():
    # 这个函数会从我们指定的 'static' 文件夹中寻找并返回 index.html 文件
    return send_from_directory(app.static_folder, 'index.html')

# 新增的路由：处理对/analyze的请求
@app.route('/analyze', methods=['POST'])
def analyze_resume():
    # 最终更新：为整个函数添加一个健壮的错误处理机制
    try:
        if 'resume' not in request.files:
            return jsonify({"error": "没有找到简历文件"}), 400
        
        resume_file = request.files['resume']
        job_description = request.form.get('jd', '')

        if resume_file.filename == '':
            return jsonify({"error": "未选择文件"}), 400
        
        if resume_file:
            resume_text = extract_text_from_pdf(resume_file.stream)
            if "读取PDF时出错" in resume_text:
                return jsonify({"error": resume_text}), 500
            
            generated_questions = get_deepseek_response(resume_text, job_description)
            
            # 检查 get_deepseek_response 函数是否返回了它自己的错误信息
            if "调用AI模型时出错" in generated_questions or "解析AI模型返回的数据时出错" in generated_questions:
                 return jsonify({"error": generated_questions}), 500

            # 如果一切正常，返回成功的结果
            return jsonify({"questions": generated_questions})
        
        # 这是一个备用的错误情况
        return jsonify({"error": "处理文件时发生未知错误"}), 500

    except Exception as e:
        # 这个 "安全网" 会捕获任何意想不到的错误
        print(f"在 /analyze 端点发生严重错误: {e}")
        # 并保证返回一个JSON，而不是一个HTML错误页面
        return jsonify({"error": "服务器内部发生严重错误，请联系管理员查看后端日志。"}), 500


def get_deepseek_response(resume_text, job_description):
    """调用 DeepSeek API 模型生成面试问题。"""
    url = "https://api.deepseek.com/chat/completions"
    
    prompt_content = f"""
    请扮演一位资深的招聘经理或技术面试官。
    我将提供一份求职者的简历文本，以及可选的目标岗位描述。
    你的任务是：
    1.  仔细分析简历中的每一部分，包括工作经历、项目经验、技能和教育背景。
    2.  结合目标岗位描述（如果提供的话），生成一系列有深度、有针对性的面试问题。
    3.  问题应该覆盖以下几个方面：
        - 针对具体工作职责和成就的深挖问题。
        - 考察技术或专业技能实际应用的问题。
        - 行为面试问题（Behavioral Questions）。
        - 如果简历中存在潜在的疑点，也需要提出相关问题。
    4.  请以清晰、有条理的格式输出，例如使用Markdown标题和列表。

    ---
    **目标岗位描述:**
    {job_description if job_description else "未提供"}

    ---
    **简历文本:**
    {resume_text}
    """

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位资深的招聘经理，擅长根据简历和职位要求提出深刻的面试问题。"},
            {"role": "user", "content": prompt_content}
        ],
        "stream": False
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content']
    except requests.exceptions.RequestException as e:
        print(f"请求 DeepSeek API 时出错: {e}")
        return f"调用AI模型时出错: {str(e)}"
    except (KeyError, IndexError) as e:
        print(f"解析 DeepSeek API 响应时出错: {e}")
        return "解析AI模型返回的数据时出错。"

def extract_text_from_pdf(pdf_file):
    """从PDF文件流中提取文本。"""
    try:
        pdf_reader = pdf.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return f"读取PDF时出错: {str(e)}"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
