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
    # --- 修复点: 合并了 binary_extensions 并添加了 .pyc ---
    "binary_extensions": [".png", ".jpg", ".svg", ".pdf", ".zip", ".exe", ".pyc"],
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

    list_keys = ["ignore_dirs", "ignore_files", "binary_extensions", "ignore_patterns"]
    for key in list_keys:
        if not isinstance(config.get(key), list):
            config[key] = [] 

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

def generate_file_tree(root_path, config):
    """遍历文件夹并生成文件树结构，遵循所有忽略规则。"""
    tree_lines = []
    
    # 从配置中安全地获取设置
    ignore_dirs_set = set(config.get('ignore_dirs', []))
    ignore_files_set = set(config.get('ignore_files', []))
    binary_extensions = config.get('binary_extensions', [])
    max_file_size_kb = config.get('max_file_size_kb', 200)

    tree_lines.append(f"📁 {os.path.basename(root_path)}/")

    # 使用一个列表来存储所有需要遍历的目录，从根目录开始
    # (path, depth)
    dir_queue = [(root_path, 0)]
    
    # 存储已经处理过的目录，防止循环引用（虽然os.walk不会，但这是一个好习惯）
    processed_dirs = set()

    # 使用字典来构建树结构，这样可以更好地处理排序和缩进
    tree = {}

    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        # --- 过滤目录 ---
        subfolders[:] = sorted([d for d in subfolders if d not in ignore_dirs_set])
        if not config.get('process_subfolders', True) and foldername != root_path:
            subfolders[:] = [] # 如果不处理子文件夹，则清空
        
        # --- 过滤文件 ---
        filtered_files = []
        for filename in sorted(filenames):
            if filename in ignore_files_set:
                continue
            if any(filename.lower().endswith(ext) for ext in binary_extensions):
                continue
            
            full_filepath = os.path.join(foldername, filename)
            try:
                if os.path.getsize(full_filepath) / 1024 > max_file_size_kb:
                    continue
                filtered_files.append(filename)
            except OSError:
                continue
        
        # --- 构建树形结构 ---
        relative_path = os.path.relpath(foldername, root_path)
        path_parts = relative_path.split(os.sep) if relative_path != '.' else []
        
        current_level = tree
        for part in path_parts:
            current_level = current_level.setdefault(f"📁 {part}", {})

        for d in subfolders:
            current_level.setdefault(f"📁 {d}", {})
        for f in filtered_files:
            current_level[f"📄 {f}"] = None # None 表示文件

    def build_tree_lines(subtree, prefix=""):
        items = sorted(subtree.keys())
        for i, key in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{key}")
            
            if subtree[key] is not None: # 如果是目录
                new_prefix = prefix + ("    " if is_last else "│   ")
                build_tree_lines(subtree[key], new_prefix)

    build_tree_lines(tree)

    # 格式化最终输出
    header = "# 项目文件树\n\n"
    body = "\n".join(tree_lines)
    return f"{header}```\n{body}\n```\n\n"

def generate_context(root_path, config):
    """遍历文件夹并生成代码上下文"""
    file_tree = generate_file_tree(root_path, config)

    full_context = [config.get('preamble_text', ''), file_tree]
    root_path = os.path.abspath(root_path)
    
    ignore_patterns = config.get('ignore_patterns', [])
    ignore_dirs_set = set(config.get('ignore_dirs', []))
    ignore_files_set = set(config.get('ignore_files', []))
    binary_extensions = config.get('binary_extensions', [])
    process_subfolders = config.get('process_subfolders', True) # 获取配置
    
    print(f"正在扫描项目: {root_path}")
    print(f"扫描模式: {'递归扫描子文件夹' if process_subfolders else '只扫描根目录'}")
    
    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        
        # --- 核心修复开始 ---
        # 1. 首先，如果在任何层级遇到忽略目录，都应该剔除，防止 os.walk 进入
        subfolders[:] = [d for d in subfolders if d not in ignore_dirs_set]
        
        # 2. 处理是否递归的逻辑
        if foldername == root_path:
            if not process_subfolders:
                subfolders[:] = [] # 如果配置不递归，清空子目录列表，os.walk 将停止深入
        # --- 核心修复结束 ---
        
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
        # 推荐使用 'utf-8'，'utf-8-sig' 主要用于解决旧版 Windows Excel 等软件的兼容性问题
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(context)
            
        print("-" * 50)
        print(f"✅ 上下文已成功生成并保存到文件: {output_filepath}")
        print(f"   文件大小: {len(context) / 1024:.2f} KB")
        print("-" * 50)
        
    except Exception as e:
        print(f"❌ 写入文件时发生错误: {e}")
        sys.exit(1)