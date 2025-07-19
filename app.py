import os
import sqlite3
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import PyPDF2 as pdf

# --- App & DB Setup ---
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24) # 用于保护会话的密钥
CORS(app)

# 数据库文件路径
DATABASE = 'database.db'

def get_db():
    """连接到数据库"""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """初始化数据库，创建表"""
    with app.app_context():
        db = get_db()
        with open('schema.sql', 'r') as f:
            db.executescript(f.read())
        db.commit()

# --- User Authentication Setup (Flask-Login) ---
login_manager = LoginManager()
login_manager.init_app(app)

class User(UserMixin):
    """用户模型"""
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    db = get_db()
    user_row = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    db.close()
    if user_row:
        return User(id=user_row['id'], username=user_row['username'])
    return None

# --- API Key Setup ---
try:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未找到 DEEPSEEK_API_KEY 环境变量")
except Exception as e:
    print(f"API密钥配置错误: {e}")

# --- Frontend & Static Routes ---
@app.route('/')
def serve_index():
    return send_from_directory(app.static_folder, 'index.html')

# --- API Routes ---
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400

    db = get_db()
    if db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone():
        db.close()
        return jsonify({"error": "用户名已存在"}), 409

    hashed_password = generate_password_hash(password)
    db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
    db.commit()
    db.close()
    return jsonify({"success": "注册成功"}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    db = get_db()
    user_row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    db.close()

    if user_row and check_password_hash(user_row['password'], password):
        user = User(id=user_row['id'], username=user_row['username'])
        login_user(user)
        return jsonify({"success": "登录成功", "username": user.username})
    
    return jsonify({"error": "用户名或密码错误"}), 401

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({"success": "已退出登录"})

@app.route('/api/check_auth')
def check_auth():
    if current_user.is_authenticated:
        return jsonify({"is_authenticated": True, "username": current_user.username})
    return jsonify({"is_authenticated": False})

@app.route('/api/history')
@login_required
def get_history():
    db = get_db()
    history_rows = db.execute(
        'SELECT questions, timestamp FROM history WHERE user_id = ? ORDER BY timestamp DESC', 
        (current_user.id,)
    ).fetchall()
    db.close()
    history = [{"questions": row['questions'], "timestamp": row['timestamp']} for row in history_rows]
    return jsonify(history)

@app.route('/api/analyze', methods=['POST'])
@login_required
def analyze_resume():
    try:
        if 'resume' not in request.files:
            return jsonify({"error": "没有找到简历文件"}), 400
        
        resume_file = request.files['resume']
        job_description = request.form.get('jd', '')

        if resume_file.filename == '':
            return jsonify({"error": "未选择文件"}), 400
        
        resume_text = extract_text_from_pdf(resume_file.stream)
        if "读取PDF时出错" in resume_text:
            return jsonify({"error": resume_text}), 500
        
        generated_questions = get_deepseek_response(resume_text, job_description)
        
        if "调用AI模型时出错" in generated_questions or "解析AI模型返回的数据时出错" in generated_questions:
             return jsonify({"error": generated_questions}), 500

        # 保存到历史记录
        db = get_db()
        db.execute('INSERT INTO history (user_id, questions) VALUES (?, ?)', (current_user.id, generated_questions))
        db.commit()
        db.close()

        return jsonify({"questions": generated_questions})

    except Exception as e:
        print(f"在 /analyze 端点发生严重错误: {e}")
        return jsonify({"error": "服务器内部发生严重错误"}), 500

# --- Helper Functions ---
def get_deepseek_response(resume_text, job_description):
    """调用 DeepSeek API 模型生成面试问题。"""
    url = "https://api.deepseek.com/chat/completions"
    prompt_content = f"请根据以下简历和职位描述，生成面试问题。\n\n职位描述:\n{job_description or '未提供'}\n\n简历文本:\n{resume_text}"
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt_content}]}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=100)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.exceptions.Timeout:
        return "调用AI模型时出错: 请求超时"
    except Exception as e:
        return f"调用AI模型时出错: {str(e)}"

def extract_text_from_pdf(pdf_file):
    """从PDF文件流中提取文本。"""
    try:
        text = ""
        pdf_reader = pdf.PdfReader(pdf_file)
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception:
        return "读取PDF时出错"

# --- Main Execution ---
if __name__ == '__main__':
    # 在第一次运行前，确保数据库和表已创建
    if not os.path.exists(DATABASE):
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
