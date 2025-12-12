import requests
import urllib3
import time
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.embeddings import Embeddings
from tqdm import tqdm 

# 禁用警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class CNAIEmbeddings(Embeddings):
    """
    适配内网 CNAI 向量化接口 (支持 Batch切分 + 并发加速)
    """
    def __init__(self, api_url: str, model_name: str, batch_size: int = 10, concurrency: int = 4):
        self.api_url = api_url
        self.model_name = model_name
        self.batch_size = batch_size
        self.concurrency = concurrency

    def _call_api_single_batch(self, texts: List[str]) -> List[List[float]]:
        """
        处理单个 batch 的请求，确保返回长度与输入长度一致
        """
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model_name,
            "input": texts
        }
        
        # 失败重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_url, 
                    headers=headers, 
                    json=payload, 
                    verify=False, 
                    timeout=60
                )
                response.raise_for_status()
                result_json = response.json()
                
                if "data" in result_json:
                    # 按照 index 排序确保顺序一致
                    data = sorted(result_json['data'], key=lambda x: x['index'])
                    embeddings = [item['embedding'] for item in data]
                    
                    # === 关键检查 ===
                    # 必须保证返回数量 == 输入数量，否则 Chroma 会报错 IndexError
                    if len(embeddings) != len(texts):
                        print(f"[Warning] API returned {len(embeddings)} vectors, expected {len(texts)}. Padding with zeros.")
                        # 如果 API 丢数据了，补全零向量防止程序崩溃（虽然这意味着数据质量下降）
                        # 假设向量维度是 1024 (根据模型调整)
                        dim = len(embeddings[0]) if embeddings else 1024
                        while len(embeddings) < len(texts):
                            embeddings.append([0.0] * dim)
                    
                    return embeddings
                else:
                    print(f"[API Error] No data field: {result_json}")
            
            except Exception as e:
                print(f"[Embedding Batch Error] Attempt {attempt+1}/{max_retries}: {e}")
                time.sleep(1) # 简单的避退
        
        # 如果重试都失败了，抛出异常，不要静默失败，否则建库是坏的
        raise RuntimeError(f"Failed to embed batch after {max_retries} attempts.")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        LangChain 标准接口：为文档列表生成向量
        实现逻辑：切分 Batch -> 并发调用 -> 顺序重组
        """
        total_docs = len(texts)
        print(f"Embedding {total_docs} documents with batch_size={self.batch_size}, concurrency={self.concurrency}...")
        
        # 1. 切分 Batches
        batches = [texts[i : i + self.batch_size] for i in range(0, total_docs, self.batch_size)]
        
        # 结果列表，预先占位，确保顺序
        batch_results = [None] * len(batches)
        
        # 2. 并发执行
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            # 提交任务，记录 future 对应的 batch 索引
            future_to_index = {
                executor.submit(self._call_api_single_batch, batch): i 
                for i, batch in enumerate(batches)
            }
            
            # === 修改处：使用 tqdm 包裹 as_completed ===
            # total: 总任务数
            # desc: 进度条左侧的描述文字
            # unit: 单位
            for future in tqdm(as_completed(future_to_index), total=len(batches), desc="Embedding", unit="batch"):
                index = future_to_index[future]
                try:
                    batch_vectors = future.result()
                    batch_results[index] = batch_vectors
                except Exception as e:
                    print(f"❌ Error processing batch {index}: {e}")
                    raise e

        # 3. 展平结果 (List[List[float]])
        final_embeddings = []
        for res in batch_results:
            if res is not None:
                final_embeddings.extend(res)
            else:
                raise RuntimeError("Missing embedding results for some batches.")

        return final_embeddings

    def embed_query(self, text: str) -> List[float]:
        """为单个查询生成向量"""
        # 查询通常只有一条，直接调用 batch 逻辑
        embeddings = self._call_api_single_batch([text])
        return embeddings[0] if embeddings else []