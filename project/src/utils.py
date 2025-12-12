import yaml
import os

def get_project_root():
    """
    动态获取项目根目录
    逻辑：当前脚本 (src/utils.py) -> 父目录 (src) -> 父目录 (ProjectRoot)
    """
    current_script_path = os.path.abspath(__file__)
    src_dir = os.path.dirname(current_script_path)
    project_root = os.path.dirname(src_dir)
    return project_root

def load_config(config_name="config.yaml"):
    """
    读取配置，并自动将所有相对路径转换为绝对路径
    """
    project_root = get_project_root()
    config_path = os.path.join(project_root, config_name)
    
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found at: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    # === 核心修改：路径标准化处理 ===
    # 遍历 config['paths'] 下的所有项
    if 'paths' in config:
        for key, path_str in config['paths'].items():
            if isinstance(path_str, str):
                # 如果是相对路径 (不以 / 开头，或者在 Windows 不带盘符)
                if not os.path.isabs(path_str):
                    # 拼接为绝对路径
                    abs_path = os.path.normpath(os.path.join(project_root, path_str))
                    config['paths'][key] = abs_path
                    print(f"[Config] Resolved relative path '{key}': {abs_path}")
                else:
                    # 如果已经是绝对路径，保持不变
                    pass
    # ============================

    return config