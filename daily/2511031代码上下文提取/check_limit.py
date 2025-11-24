import os
import sys
import re

# ================= 配置区域 =================
# 如果你想在代码里直接指定路径，请修改下面两个变量
# 如果保持为 None，脚本会自动去读取同级目录下的 config.yaml
MANUAL_PROJECT_PATH = None  # 例如: r"D:\Data\MyProject"
MANUAL_OUTPUT_FILENAME = None # 例如: "context.txt"

# ================= 常量定义 =================
LIMIT_HTTP_KB = 36
LIMIT_HTTPS_KB = 100
LIMIT_GEMINI_TOKEN = 1000000

# HTTP 头的预留开销（估算值，请求体还需要包含JSON结构等，建议预留 1-2KB）
OVERHEAD_BYTES = 1024 

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'

    # Windows CMD 默认不支持 ANSI 颜色，做个简单兼容处理
    if os.name == 'nt':
        try:
            import colorama
            colorama.init()
        except ImportError:
            HEADER = OKBLUE = OKGREEN = WARNING = FAIL = ENDC = ''

def parse_yaml_simple(yaml_path):
    """
    简易 YAML 解析器，避免引入 PyYAML 依赖。
    针对你提供的 config.yaml 格式进行解析。
    """
    config = {}
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            content = f.readlines()
            
        for line in content:
            line = line.strip()
            if line.startswith('#') or not line:
                continue
            
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()
                # 去除可能的引号
                value = value.strip("'").strip('"')
                config[key] = value
    except Exception as e:
        print(f"{bcolors.FAIL}[Error] 读取 config.yaml 失败: {e}{bcolors.ENDC}")
        sys.exit(1)
    return config

def estimate_gemini_tokens(text):
    """
    估算 Gemini Token。
    Gemini 使用 SentencePiece tokenizer。
    官方经验值：
    - 英语: 1 token ≈ 4 chars
    - 中文/代码: 1 token ≈ 1.5 ~ 2 chars (取决于复杂程度)
    
    为了安全起见，我们使用较保守的估算：
    平均 1 token ≈ 2.5 bytes (UTF-8)
    或者粗略统计：中文字数 + (英文字数/3)
    """
    # 方法1：基于字符长度的简单混合估算
    # 这是一个经验公式，用于快速判断
    total_len = len(text)
    # 统计非ASCII字符（粗略当作中文）
    non_ascii_count = sum(1 for c in text if ord(c) > 127)
    ascii_count = total_len - non_ascii_count
    
    # 中文通常 1字=1~1.5 token，英文 1词=1.3 token (约4字符)
    estimated_tokens = int(non_ascii_count * 1.2 + ascii_count / 3.5)
    
    return estimated_tokens

def get_file_info(file_path):
    if not os.path.exists(file_path):
        print(f"{bcolors.FAIL}[Error] 文件不存在: {file_path}{bcolors.ENDC}")
        return None

    try:
        # 获取文件字节大小
        file_size_bytes = os.path.getsize(file_path)
        
        # 读取内容用于计算 Token
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        token_count = estimate_gemini_tokens(content)
        
        return {
            "size_bytes": file_size_bytes,
            "token_count": token_count,
            "content_len": len(content)
        }
    except Exception as e:
        print(f"{bcolors.FAIL}[Error] 读取文件出错: {e}{bcolors.ENDC}")
        return None

def format_size(size_bytes):
    return f"{size_bytes / 1024:.2f} KB"

def main():
    print(f"{bcolors.HEADER}=== Gemini 上下文及网络流量检查器 ==={bcolors.ENDC}")
    
    # 1. 确定路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(current_dir, 'config.yaml')
    
    target_file_path = ""

    if MANUAL_PROJECT_PATH and MANUAL_OUTPUT_FILENAME:
        print(f"[Info] 使用脚本内硬编码路径")
        target_file_path = os.path.join(MANUAL_PROJECT_PATH, MANUAL_OUTPUT_FILENAME)
    elif os.path.exists(config_path):
        print(f"[Info] 读取配置文件: {config_path}")
        config = parse_yaml_simple(config_path)
        
        p_path = config.get('project_path', '.')
        f_name = config.get('output_filename', '')
        
        # 处理相对路径
        if not os.path.isabs(p_path):
            p_path = os.path.join(current_dir, p_path)
            
        target_file_path = os.path.join(p_path, f_name)
    else:
        print(f"{bcolors.FAIL}[Error] 未找到 config.yaml 且未设置硬编码路径。{bcolors.ENDC}")
        sys.exit(1)

    # 规范化路径（处理 Windows 的反斜杠等）
    target_file_path = os.path.normpath(target_file_path)
    print(f"[Check] 目标文件: {target_file_path}")

    # 2. 获取信息
    info = get_file_info(target_file_path)
    if not info:
        return

    size_bytes = info['size_bytes']
    tokens = info['token_count']

    # 3. 判定逻辑
    print("-" * 40)
    print(f"文件大小 (Bytes): {size_bytes} B")
    print(f"文件大小 (KB)   : {format_size(size_bytes)}")
    print(f"估算 Tokens     : ~{tokens} (Gemini 1M Limit)")
    print("-" * 40)

    # 检查 HTTP 36KB
    limit_http_bytes = LIMIT_HTTP_KB * 1024 - OVERHEAD_BYTES
    if size_bytes > limit_http_bytes:
        print(f"HTTP ({LIMIT_HTTP_KB}KB) : {bcolors.FAIL}❌ 超限 (超出约 {format_size(size_bytes - limit_http_bytes)}){bcolors.ENDC}")
        print(f"   -> 警告: 在 HTTP 协议下会被 Proxy 强制切断")
    else:
        print(f"HTTP ({LIMIT_HTTP_KB}KB) : {bcolors.OKGREEN}✅ 安全{bcolors.ENDC}")

    # 检查 HTTPS 100KB
    limit_https_bytes = LIMIT_HTTPS_KB * 1024 - OVERHEAD_BYTES
    if size_bytes > limit_https_bytes:
        print(f"HTTPS ({LIMIT_HTTPS_KB}KB): {bcolors.FAIL}❌ 超限 (超出约 {format_size(size_bytes - limit_https_bytes)}){bcolors.ENDC}")
        print(f"   -> 警告: 在 HTTPS 协议下会被 Proxy 强制切断")
    else:
        print(f"HTTPS ({LIMIT_HTTPS_KB}KB): {bcolors.OKGREEN}✅ 安全{bcolors.ENDC}")

    # 检查 Gemini Token
    if tokens > LIMIT_GEMINI_TOKEN:
        print(f"Gemini 1M     : {bcolors.FAIL}❌ 超限{bcolors.ENDC}")
    else:
        # 计算占用比例
        percent = (tokens / LIMIT_GEMINI_TOKEN) * 100
        print(f"Gemini 1M     : {bcolors.OKGREEN}✅ 安全 (占用约 {percent:.2f}%){bcolors.ENDC}")

    print("-" * 40)
    
    # 总结
    if size_bytes > limit_https_bytes:
        print(f"{bcolors.FAIL}【最终结论】无法发送！文件过大，超过内网 100KB 限制。{bcolors.ENDC}")
        print("建议：请分段发送，或压缩内容。")
    elif size_bytes > limit_http_bytes:
         print(f"{bcolors.WARNING}【最终结论】仅限 HTTPS 发送。超过 36KB 但小于 100KB。{bcolors.ENDC}")
    else:
        print(f"{bcolors.OKGREEN}【最终结论】可以发送。{bcolors.ENDC}")

if __name__ == "__main__":
    main()