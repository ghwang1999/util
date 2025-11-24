import os
import argparse
import json
import sys

# 默认配置
DEFAULT_CONFIG = {
    "output_filename": "ai_context_snapshot.txt",
    "ignore_dirs": [
        ".git", "node_modules", "__pycache__", "dist", "build", 
        ".vscode", ".idea", "venv", "env", "logs"
    ],
    "ignore_files": [
        ".gitignore", "README.md", "LICENSE", "package-lock.json", 
        "context_generator.py", "config.json"
    ],
    "binary_extensions": [
        ".png", ".jpg", ".jpeg", ".svg", ".ico", ".pdf", ".zip", 
        ".tar", ".gz", ".exe", ".dll", ".bin", ".mp4", ".mov"
    ],
    "max_file_size_kb": 200,
    "preamble_text": "# Project Context Snapshot\n\n",
    "ignore_patterns": [] # 新增：用于屏蔽特定词语或句子的列表
}

def load_config(root_path):
    """尝试从项目根目录加载配置，并合并默认配置。"""
    config_path = os.path.join(root_path, 'config.json')
    user_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
            print(f"✅ 成功加载配置文件: {config_path}")
        except json.JSONDecodeError:
            print(f"❌ 错误: 配置文件 '{config_path}' 格式不正确，将使用默认配置。")
        except Exception as e:
            print(f"❌ 错误: 读取配置文件时发生意外错误: {e}")
            
    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    return config

def get_syntax_lang(filepath):
    """根据文件扩展名返回代码块语言提示"""
    extension_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
        '.jsx': 'jsx', '.tsx': 'tsx', '.html': 'html',
        '.css': 'css', '.scss': 'scss', '.json': 'json',
        '.md': 'markdown', '.java': 'java', '.go': 'go',
        '.sh': 'bash', '.yaml': 'yaml', '.yml': 'yaml',
    }
    ext = os.path.splitext(filepath)[1].lower()
    return extension_map.get(ext, '')

def filter_content(content, patterns):
    """根据提供的模式列表过滤文件内容。"""
    if not patterns:
        return content
    
    lines = content.splitlines()
    # 只保留不包含任何屏蔽模式的行
    filtered_lines = [line for line in lines if not any(pattern in line for pattern in patterns)]
    return "\n".join(filtered_lines)

def generate_context(root_path, config):
    """遍历文件夹并生成代码上下文"""
    full_context = [config['preamble_text']]
    root_path = os.path.abspath(root_path)
    ignore_patterns = config.get('ignore_patterns', [])
    
    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        
        subfolders[:] = [d for d in subfolders if d not in config['ignore_dirs']]

        for filename in filenames:
            
            full_filepath = os.path.join(foldername, filename)
            relative_path = os.path.relpath(full_filepath, root_path)
            
            if filename in config['ignore_files']: continue
            if any(relative_path.lower().endswith(ext) for ext in config['binary_extensions']): continue
            
            try:
                if os.path.getsize(full_filepath) / 1024 > config['max_file_size_kb']:
                    print(f"跳过过大文件: {relative_path}")
                    continue
            except Exception:
                continue

            try:
                with open(full_filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # --- 新增：内容过滤 ---
                filtered_content = filter_content(content, ignore_patterns)
                # ---------------------
                
                lang = get_syntax_lang(relative_path)
                
                block = (
                    f"{relative_path}\n"
                    f"```{lang}\n"
                    f"{filtered_content.strip()}\n"
                    f"```\n\n"
                )
                full_context.append(block)
                
            except UnicodeDecodeError:
                pass
            except Exception as e:
                print(f"处理文件 {relative_path} 时发生错误: {e}")

    return "".join(full_context)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为 AI 上下文生成项目代码快照。")
    parser.add_argument('project_path', nargs='?', default='.', help='项目文件夹的路径 (例如: . 或 /path/to/my/project)')
    args = parser.parse_args()
    
    project_root = args.project_path
    
    config = load_config(project_root)
    output_filename = config['output_filename']
    
    print(f"正在扫描项目: {os.path.abspath(project_root)}")
    
    context = generate_context(project_root, config)
    
    try:
        output_filepath = os.path.join(project_root, output_filename)
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(context)
            
        print("-" * 50)
        print(f"✅ 上下文已成功生成并保存到文件: {output_filepath}")
        print(f"文件大小: {len(context) / 1024:.2f} KB")
        print("请复制该文件的内容用于 AI 交流。")
        print("-" * 50)
        
    except Exception as e:
        print(f"❌ 写入文件时发生错误: {e}")
        sys.exit(1)