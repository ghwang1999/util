import os
import argparse
import sys
import fnmatch

try:
    import yaml
except ImportError:
    print("❌ 错误: PyYAML 库未安装。请运行 'pip install PyYAML' 来安装它。")
    sys.exit(1)

# --- 默认全局配置 ---
DEFAULT_CONFIG = {
    "project_path": ".",
    "output_filename": "ai_context_snapshot.txt",
    "max_file_size_kb": 200,
    "process_subfolders": True,
    "tree_only": False,
    # 统一的黑名单：支持文件夹名、文件名、通配符
    "ignore": [
        ".git", "node_modules", "__pycache__", "dist", "build", ".vscode", "venv", ".idea",
        "*.pyc", "*.png", "*.jpg", "*.svg", "*.exe", "*.zip", "*.pdf", "package-lock.json"
    ],
    # 统一的白名单：如果设置了内容，则只扫描匹配的路径；为空则扫描所有
    "include": [], 
    "preamble_text": "# Project Context Snapshot\n\n",
    "ignore_patterns": [] # 内容过滤
}

PROJECT_CONFIG_NAME = ".context_rules.yaml"  # 项目文件夹内的配置文件名

def merge_config(base_config, new_config):
    """合并配置：列表追加，其他类型覆盖"""
    if not new_config:
        return base_config
    
    merged = base_config.copy()
    for key, value in new_config.items():
        # 处理 YAML 中列表全被注释导致 value 为 None 的情况
        if value is None:
            if isinstance(base_config.get(key), list):
                value = []
            else:
                continue # 如果不是列表且为None，通常忽略或保持默认
        
        # 列表类型 -> 追加 (去重)
        if isinstance(value, list) and isinstance(merged.get(key), list):
            # 简单的去重合并，保持顺序
            current_list = merged[key]
            for item in value:
                if item not in current_list:
                    current_list.append(item)
        # 其他类型 -> 覆盖
        else:
            merged[key] = value
    return merged

def load_config(script_dir, project_root=None):
    """加载全局配置，并尝试加载项目级配置"""
    # 1. 加载默认配置
    config = DEFAULT_CONFIG.copy()
    
    # 2. 加载全局 config.yaml
    global_config_path = os.path.join(script_dir, 'config.yaml')
    if os.path.exists(global_config_path):
        try:
            with open(global_config_path, 'r', encoding='utf-8') as f:
                global_yml = yaml.safe_load(f)
                config = merge_config(config, global_yml)
            print(f"✅ 已加载全局配置: {global_config_path}")
        except Exception as e:
            print(f"⚠️ 加载全局配置出错: {e}")

    # 3. 加载项目级配置 (如果存在)
    if project_root:
        project_config_path = os.path.join(project_root, PROJECT_CONFIG_NAME)
        if os.path.exists(project_config_path):
            try:
                with open(project_config_path, 'r', encoding='utf-8') as f:
                    proj_yml = yaml.safe_load(f)
                    config = merge_config(config, proj_yml)
                print(f"✅ 已加载项目级配置: {project_config_path}")
            except Exception as e:
                print(f"⚠️ 加载项目配置出错: {e}")
    
    # 确保关键字段是列表
    for key in ["ignore", "include", "ignore_patterns"]:
        if config.get(key) is None: config[key] = []
        
    return config

def should_ignore(name, relative_path, config):
    """检查文件/文件夹是否应该被忽略 (黑名单)"""
    ignore_rules = config.get('ignore', [])
    
    # 1. 检查名称匹配 (如 'node_modules', '*.pyc')
    for pattern in ignore_rules:
        if fnmatch.fnmatch(name, pattern):
            return True
            
    # 2. 检查路径匹配 (如 'src/temp/*')
    # 将路径分隔符统一为 /
    normalized_path = relative_path.replace(os.sep, '/')
    for pattern in ignore_rules:
        if fnmatch.fnmatch(normalized_path, pattern):
            return True
            
    return False

def should_include(name, relative_path, config):
    """检查文件/文件夹是否在白名单中 (修正版)"""
    include_rules = config.get('include', [])
    
    # 如果白名单为空，默认全选 (返回 True)
    if not include_rules:
        return True
        
    normalized_path = relative_path.replace(os.sep, '/')
    
    for pattern in include_rules:
        # 去除 pattern 末尾的斜杠，防止 "graphrag/" 匹配不到 "graphrag"
        clean_pattern = pattern.rstrip('/')
        
        # 1. 文件名或路径精确匹配 / 通配符匹配
        # 情况：include: ["*.py"], 当前是 test.py -> 命中
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(normalized_path, pattern):
            return True
        
        # 2. [递归向下] 还没走到目标文件夹，但当前是必经之路
        # 情况：include: ["src/utils"], 当前是 src -> 必须命中，否则进不去
        # 判断：pattern 是否以 "src/" 开头
        if clean_pattern.startswith(normalized_path + '/'):
            return True

        # 3. [递归向上] 已经进入了目标文件夹，其子内容都要包含 (这是之前缺失的逻辑！)
        # 情况：include: ["graphrag"], 当前是 graphrag/index -> 必须命中
        # 判断：当前路径 是否以 "graphrag/" 开头
        if normalized_path.startswith(clean_pattern + '/'):
            return True
            
    return False

def filter_content(content, patterns):
    if not patterns: return content
    lines = content.splitlines()
    filtered_lines = [line for line in lines if not any(p in line for p in patterns)]
    return "\n".join(filtered_lines)

def generate_file_tree(root_path, config):
    tree_lines = []
    tree_lines.append(f"📁 {os.path.basename(root_path)}/")
    
    ignore_rules = config.get('ignore', [])
    
    tree = {}
    
    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        rel_dir = os.path.relpath(foldername, root_path)
        if rel_dir == '.': rel_dir = ''
        
        # --- 过滤目录 (原地修改 subfolders) ---
        # 1. 黑名单过滤
        subfolders[:] = [d for d in subfolders if not should_ignore(d, os.path.join(rel_dir, d), config)]
        # 2. 白名单过滤
        if config.get('include'):
             subfolders[:] = [d for d in subfolders if should_include(d, os.path.join(rel_dir, d), config)]
        
        # 如果不处理子文件夹，且当前是根目录，清空子目录
        if not config.get('process_subfolders', True) and foldername == root_path:
            subfolders[:] = []

        # --- 过滤文件 ---
        filtered_files = []
        for filename in sorted(filenames):
            file_rel_path = os.path.join(rel_dir, filename)
            
            # 黑名单
            if should_ignore(filename, file_rel_path, config): continue
            # 白名单
            if not should_include(filename, file_rel_path, config): continue
            
            # 大小检查 (树结构可以不检查大小，也可以检查，这里为了简洁只在读取时严格检查)
            filtered_files.append(filename)

        # --- 构建树 ---
        path_parts = rel_dir.split(os.sep) if rel_dir else []
        current_level = tree
        for part in path_parts:
            current_level = current_level.setdefault(f"📁 {part}", {})
            
        for d in subfolders:
            current_level.setdefault(f"📁 {d}", {})
        for f in filtered_files:
            current_level[f"📄 {f}"] = None

    def build_tree_lines(subtree, prefix=""):
        items = sorted(subtree.keys())
        for i, key in enumerate(items):
            is_last = (i == len(items) - 1)
            connector = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{connector}{key}")
            if subtree[key] is not None:
                new_prefix = prefix + ("    " if is_last else "│   ")
                build_tree_lines(subtree[key], new_prefix)

    build_tree_lines(tree)
    return "# Project Tree\n\n```\n" + "\n".join(tree_lines) + "\n```\n\n"

def generate_context(root_path, config):
    full_context = [config.get('preamble_text', ''), generate_file_tree(root_path, config)]

    # 如果开启了仅树模式，直接返回
    if config.get('tree_only', False):
        print("🌳 已开启 tree-only 模式：跳过文件内容读取。")
        return "".join(full_context)
    
    print(f"开始扫描: {root_path}")
    
    for foldername, subfolders, filenames in os.walk(root_path, topdown=True):
        rel_dir = os.path.relpath(foldername, root_path)
        if rel_dir == '.': rel_dir = ''
        
        # --- 过滤目录 ---
        subfolders[:] = [d for d in subfolders if not should_ignore(d, os.path.join(rel_dir, d), config)]
        if config.get('include'):
             subfolders[:] = [d for d in subfolders if should_include(d, os.path.join(rel_dir, d), config)]
        
        if foldername == root_path and not config.get('process_subfolders', True):
             subfolders[:] = []

        # --- 处理文件 ---
        for filename in filenames:
            file_rel_path = os.path.join(rel_dir, filename)
            
            # 过滤
            if should_ignore(filename, file_rel_path, config): continue
            if not should_include(filename, file_rel_path, config): continue
            
            full_filepath = os.path.join(foldername, filename)
            
            try:
                if os.path.getsize(full_filepath) / 1024 > config.get('max_file_size_kb'):
                    print(f"  - 跳过大文件: {file_rel_path}")
                    continue
                
                with open(full_filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                content = filter_content(content, config.get('ignore_patterns', []))
                ext = os.path.splitext(filename)[1]
                
                block = f"--- {file_rel_path} ---\n```{ext.lstrip('.')}\n{content.strip()}\n```\n\n"
                full_context.append(block)
                
            except Exception:
                pass
                
    return "".join(full_context)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Context Generator")
    parser.add_argument('path', nargs='?', default=None)
    parser.add_argument('-t', '--tree-only', action='store_true', help='开启后只输出文件树，不包含文件内容')
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. 初始加载获取 project_path
    temp_config = load_config(script_dir)
    project_path = args.path if args.path else temp_config.get('project_path', '.')
    
    if not os.path.isabs(project_path):
        project_path = os.path.abspath(os.path.join(script_dir, project_path))
        
    if not os.path.isdir(project_path):
        print(f"❌ 路径不存在: {project_path}")
        sys.exit(1)
        
    # 2. 重新加载，这次传入 project_path 以读取项目级配置
    final_config = load_config(script_dir, project_path)
    
    # 将命令行参数应用到配置中
    if args.tree_only:
        final_config['tree_only'] = True

    # 更新最终路径
    final_config['project_path'] = project_path 
    
    output_content = generate_context(project_path, final_config)
    
    out_file = os.path.join(project_path, final_config['output_filename'])
    with open(out_file, 'w', encoding='utf-8-sig') as f:
        f.write(output_content)
        
    print(f"\n✅ 完成! 输出文件: {out_file} ({len(output_content)/1024:.1f} KB)")