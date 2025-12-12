import os
import shutil
import torch
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from sentence_transformers import CrossEncoder

# 引入自定义 Embedding
from src.cnai_embedding import CNAIEmbeddings
from src.gpu_manager import GpuAdaptiveManager

class RagEngine:
    def __init__(self, config):
        self.config = config
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.persist_dir = config['paths']['vector_db_dir']

        # 初始化 GPU 管理器
        self.gpu_manager = GpuAdaptiveManager(config)
        
        # 1. 初始化 Embedding 模型 (根据配置切换)
        mode = config['models']['embedding_mode']
        if mode == 'internal':
            int_conf = config['models']['internal_embedding']
            print(f"Loading Internal Embedding ({int_conf['model_name']}) "
                  f"Batch={int_conf.get('batch_size', 10)}, "
                  f"Concurrent={int_conf.get('embed_concurrency', 4)}...")
            
            self.embeddings = CNAIEmbeddings(
                api_url=int_conf['api_url'],
                model_name=int_conf['model_name'],
                # === 传入新参数 ===
                batch_size=int_conf.get('batch_size', 10),
                concurrency=int_conf.get('embed_concurrency', 16)
            )
        else:
            print(f"Loading Local Embedding Model ({config['models']['local_embedding_path']})...")
            self.embeddings = HuggingFaceEmbeddings(
                model_name=config['models']['local_embedding_path'],
                model_kwargs={'device': self.device},
                encode_kwargs={'normalize_embeddings': True}
            )
        
        # 2. Reranker 初始化
        self.enable_rerank = config['execution']['enable_rerank']
        if self.enable_rerank:
            # 注意：这里加载模型本身可能就会 OOM，但初始化通常是单线程的，这里暂不包裹
            print(f"Loading Reranker Model...")
            self.reranker = CrossEncoder(
                config['models']['rerank_model_path'], 
                max_length=512, 
                device=self.device
            )
        else:
            self.reranker = None
            
        self.vector_store = None

    def build_index(self, chunks):
        """构建向量索引"""
        print("Building Vector Store...")
        # Chroma 会自动调用 self.embeddings.embed_documents
        self.vector_store = Chroma.from_documents(
            documents=chunks,
            embedding=self.embeddings,
            persist_directory=self.persist_dir
        )
        print("Vector Store built.")

    def load_index(self):
        if os.path.exists(self.persist_dir):
            self.vector_store = Chroma(
                persist_directory=self.persist_dir, 
                embedding_function=self.embeddings
            )
            return True
        return False

    def retrieve(self, query):
        if not self.vector_store:
            raise ValueError("Vector store not initialized!")
            
        # 1. 向量粗排 (通常 Chroma 跑在 CPU 或内存，不太容易 OOM，除非量巨大)
        # 如果使用本地 Embedding 模型，这里也建议保护一下
        if self.config['models']['embedding_mode'] == 'local':
             # 定义一个内部函数来执行搜索
            def _do_search():
                return self.vector_store.similarity_search(query, k=self.config['rag']['top_k_retrieval'])
            
            # 使用保护执行
            docs = self.gpu_manager.run_with_protection(_do_search)
        else:
            # 内网模式直接调，不消耗本地显存
            docs = self.vector_store.similarity_search(query, k=self.config['rag']['top_k_retrieval'])
        
        # 2. Rerank (显存消耗大户)
        if not self.enable_rerank:
            top_k_final = self.config['rag']['top_k_rerank']
            return docs[:top_k_final]
            
        doc_texts = [d.page_content for d in docs]
        if not doc_texts: return []
            
        pairs = [[query, doc_text] for doc_text in doc_texts]
        
        # === 核心修改：使用 GPU 管理器执行推理 ===
        def _do_rerank():
            return self.reranker.predict(pairs)

        # 这一步会自动处理 OOM -> 降级 -> 重试
        scores = self.gpu_manager.run_with_protection(_do_rerank)
        # ======================================
        
        scored_docs = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
        top_k_final = self.config['rag']['top_k_rerank']
        final_docs = [doc for doc, score in scored_docs[:top_k_final]]
        
        return final_docs