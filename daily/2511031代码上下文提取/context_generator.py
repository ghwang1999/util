import os
import argparse
import sys
try:
    import yaml # 导入 PyYAML 库
except ImportError:
    print("❌ 错误: PyYAML 库未安装。请运行 'pip install PyYAML' 来安装它。")
    sys.exit(1)

# 默认配置
DEFAULT_CONFIG = {
    "project_path": ".",
    "output_filename": "ai_context_snapshot.txt",
    "ignore_dirs": [".git", "node_modules", "__pycache__", "dist", "build", ".vscode", "venv"],
    "ignore_files": ["context_generator.py", "config.yaml", "config.yml"],
    "binary_extensions": [".png", ".jpg", ".svg", ".pdf", ".zip", ".exe"],
    "max_file_size_kb": 200,
    "preamble_text": "# Project Context Snapshot\n\n",
    "ignore_patterns": [],
    "process_subfolders": True
}

def load_config(base_path):
    """尝试从指定目录加载 YAML 配置，并合并默认配置。"""
    config = DEFAULT_CONFIG.copy()
    config_path_yaml = os.path.join(base_path, 'config.yaml')
    config_path_yml = os.path.join(base_path, 'config.yml')
    
    config_path = None
    if os.path.exists(config_path_yaml):
        config_path = config_path_yaml
    elif os.path.exists(config_path_yml):
        config_path = config_path_yml

    if config_path:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
                if user_config:
                    config.update(user_config)
            print(f"✅ 成功加载配置文件: {config_path}")
        except yaml.YAMLError as e:
            print(f"❌ 错误: 配置文件 '{config_path}' 格式不正确: {e}")
        except Exception as e:
            print(f"❌ 错误: 读取配置文件时发生意外错误: {e}")
    else:
        print("ℹ️ 未找到 config.yaml 或 config.yml，将使用默认配置。")

    # --- 主要修复点在这里 ---
    # 确保所有期望是列表的配置项，如果为 None，则变为空列表
    list_keys = ["ignore_dirs", "ignore_files", "binary_extensions", "ignore_patterns"]
    for key in list_keys:
        if not isinstance(config.get(key), list):
            config[key] = [] # 如果用户配置为None或非列表，强制变为空列表

    # 确保输出文件本身总是在忽略列表中
    output_file = config.get("output_filename")
    if output_file and output_file not in config["ignore_files"]:
        config["ignore_files"].append(output_file)

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
    filtered_lines = [line for line in lines if not any(pattern in line for pattern in patterns)]
    return "\n".join(filtered_lines)


def generate_context(root_path, config):
    """遍历文件夹并生成代码上下文"""
    full_context = [config.get('preamble_text', '')] # 使用 .get 保证安全
    root_path = os.path.abspath(root_path)
    
    # 从配置中安全地获取列表
    ignore_patterns = config.get('ignore_patterns', [])
    ignore_dirs_set = set(config.get('ignore_dirs', []))
    ignore_files_set = set(config.get('ignore_files', []))
    binary_extensions = config.get('binary_extensions', [])
    
    print(f"正在扫描项目: {root_path}")
    print(f"扫描模式: {'递归扫描子文件夹' if config.get('process_subfolders', True) else '只扫描根目录'}")
    
    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        
        # 修改这里的逻辑，确保只在根目录时才进行子目录筛选，以支持非递归模式
        if foldername == root_path:
            if not config.get('process_subfolders', True):
                subfolders[:] = [] # 清空子目录，阻止递归
            else:
                subfolders[:] = [d for d in subfolders if d not in ignore_dirs_set]
        
        for filename in filenames:
            if filename in ignore_files_set:
                continue
            
            full_filepath = os.path.join(foldername, filename)
            relative_path = os.path.relpath(full_filepath, root_path)
            
            if any(relative_path.lower().endswith(ext) for ext in binary_extensions):
                continue
            
            try:
                if os.path.getsize(full_filepath) / 1024 > config.get('max_file_size_kb', 200):
                    print(f"  - 跳过过大文件: {relative_path}")
                    continue
            except Exception:
                continue

            try:
                with open(full_filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                filtered_content = filter_content(content, ignore_patterns)
                lang = get_syntax_lang(relative_path)
                
                block = f"--- {relative_path} ---\n```{lang}\n{filtered_content.strip()}\n```\n\n"
                full_context.append(block)
                
            except Exception:
                pass

    return "".join(full_context)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="为 AI 上下文生成项目代码快照。")
    parser.add_argument('path', nargs='?', default=None, help='(可选) 要扫描的项目文件夹路径，会覆盖配置文件中的设置。')
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config = load_config(script_dir)
    
    project_root_path = args.path if args.path else config.get('project_path', '.')
    
    # 路径解析：如果路径不是绝对路径，则认为是相对于脚本/配置文件目录的
    if not os.path.isabs(project_root_path):
        project_root = os.path.abspath(os.path.join(script_dir, project_root_path))
    else:
        project_root = project_root_path

    if args.path:
        print(f"ℹ️ 使用命令行参数指定的项目路径: {project_root}")
    else:
        print(f"ℹ️ 使用配置文件指定的项目路径: {project_root}")
        
    if not os.path.isdir(project_root):
        print(f"❌ 错误: 指定的路径 '{project_root}' 不是一个有效的文件夹。")
        sys.exit(1)

    context = generate_context(project_root, config)
    output_filename = config.get('output_filename', 'ai_context_snapshot.txt')
    
    try:
        output_filepath = os.path.join(project_root, output_filename)
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(context)
            
        print("-" * 50)
        print(f"✅ 上下文已成功生成并保存到文件: {output_filepath}")
        print(f"   文件大小: {len(context) / 1024:.2f} KB")
        print("-" * 50)
        
    except Exception as e:
        print(f"❌ 写入文件时发生错误: {e}")
        sys.exit(1)