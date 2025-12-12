import sys
import os
import pandas as pd
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# 引用 src
sys.path.append(os.path.join(os.getcwd(), 'src'))

from src.utils import load_config
from src.data_loader import DataLoader, ExcelHandler
from src.rag_engine import RagEngine
from src.generator import LLMGenerator

# 全局变量，方便 Worker 访问
rag_engine = None
llm_generator = None

def process_single_case(index, question):
    """
    单个问题的处理函数，供线程池调用
    :param index: DataFrame 的索引 (用于保持顺序)
    :param question: 问题文本
    :return: (index, answer)
    """
    try:
        if pd.isna(question) or str(question).strip() == "":
            return index, ""
            
        # 1. 检索 (如果使用了内网Embedding，这里会走内网HTTP请求)
        # 注意：如果开启了本地模型 Rerank，多线程同时调用 GPU 可能会有争抢，
        # 但通常 PyTorch 推理在多线程下是安全的(会排队)，或者建议在 Config 关闭 Rerank
        relevant_docs = rag_engine.retrieve(question)
        
        # 2. LLM 生成 (高并发网络请求)
        answer = llm_generator.generate_answer(question, relevant_docs)
        
        return index, answer
    except Exception as e:
        return index, f"Error: {str(e)}"

def setup_global_proxy(config):
    """全局设置不使用代理，避免多线程环境下的竞争条件"""
    no_proxy_ips = config['llm_config']['internal'].get('no_proxy_ips', '')
    if no_proxy_ips:
        os.environ['no_proxy'] = no_proxy_ips
        os.environ['NO_PROXY'] = no_proxy_ips
        print(f"Global Proxy Set: NO_PROXY={no_proxy_ips}")

def main():
    global rag_engine, llm_generator
    
    # 1. 读取配置
    config = load_config("config.yaml")
    
    # 2. 设置全局代理
    setup_global_proxy(config)
    
    # 3. 初始化模块 (保持不变)
    data_loader = DataLoader(config)
    excel_handler = ExcelHandler(config)
    rag_engine = RagEngine(config)
    llm_generator = LLMGenerator(config)

    # 4. 向量库准备 (保持不变)
    if not rag_engine.load_index():
        print("Creating Vector DB...")
        chunks = data_loader.load_and_chunk_corpus()
        rag_engine.build_index(chunks)
    else:
        print("Loaded existing Vector DB.")

    # 5. 读取数据
    df = excel_handler.read_questions()
    
    # === 修改处：从配置读取列名 ===
    question_col_name = config['excel_columns']['question_col']  # 读取 "问题"
    output_col_name = config['excel_columns']['output_col']      # 读取 "gen_answer"
    
    print(f"Target Column for Questions: [{question_col_name}]")
    
    # 检查列是否存在
    if question_col_name not in df.columns:
        print(f"❌ Error: Column '{question_col_name}' not found in Excel.")
        print(f"   Available columns: {list(df.columns)}")
        # 打印前几个字符帮助排查（防止有隐藏空格，如 "问题 "）
        return

    # 初始化结果列
    if output_col_name not in df.columns:
        df[output_col_name] = ""

    # 6. 并发处理
    concurrency = config['execution']['concurrency']
    print(f"Starting RAG generation with concurrency = {concurrency} ...")
    
    tasks = []
    for index, row in df.iterrows():
        # 获取问题文本
        q_text = row[question_col_name]
        tasks.append((index, q_text))

    results_buffer = {} 

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_index = {
            executor.submit(process_single_case, idx, q): idx 
            for idx, q in tasks
        }
        
        for future in tqdm(as_completed(future_to_index), total=len(tasks), desc="Processing"):
            idx, answer = future.result()
            results_buffer[idx] = answer

    # 7. 按顺序回填结果
    print("Writing results back to DataFrame...")
    for idx, answer in results_buffer.items():
        # 使用配置的输出列名
        df.at[idx, output_col_name] = answer

    # 8. 保存
    excel_handler.save_results(df)
    print("All Done.")

if __name__ == "__main__":
    main()