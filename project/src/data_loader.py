import os
import glob
import pandas as pd
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

class DataLoader:
    def __init__(self, config):
        self.corpus_dir = config['paths']['corpus_dir']
        self.chunk_size = config['rag']['chunk_size']
        self.chunk_overlap = config['rag']['chunk_overlap']

    def load_and_chunk_corpus(self):
        """读取文件夹下所有txt并切片"""
        documents = []
        files = glob.glob(os.path.join(self.corpus_dir, "*.txt"))
        
        print(f"Found {len(files)} files in {self.corpus_dir}")
        
        for file_path in files:
            try:
                loader = TextLoader(file_path, encoding='utf-8')
                documents.extend(loader.load())
            except Exception as e:
                print(f"Error loading {file_path}: {e}")

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        texts = text_splitter.split_documents(documents)
        print(f"Generated {len(texts)} chunks.")
        return texts

class ExcelHandler:
    def __init__(self, config):
        self.input_path = config['paths']['test_case_path']
        
        # 尝试从配置读取输出路径
        # 如果配置里没有写 output_path，则自动生成一个默认名
        configured_output = config['paths'].get('output_path')
        
        if configured_output:
            self.output_path = configured_output
        else:
            # 自动生成：原文件名.xlsx -> 原文件名_gen_answers.xlsx
            dir_name = os.path.dirname(self.input_path)
            base_name = os.path.basename(self.input_path)
            name_part, ext_part = os.path.splitext(base_name)
            new_name = f"{name_part}_gen_answers{ext_part}"
            self.output_path = os.path.join(dir_name, new_name)
            print(f"[Config] No output_path specified. Will save to: {self.output_path}")

    def read_questions(self):
        """读取原始 Excel (只读模式)"""
        print(f"Reading test cases from: {self.input_path}")
        return pd.read_excel(self.input_path)
    
    def save_results(self, df):
        """保存 DataFrame 到新的 Excel 文件"""
        # 确保输出目录存在
        output_dir = os.path.dirname(self.output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        try:
            df.to_excel(self.output_path, index=False)
            print(f"✅ Success! Results saved to NEW file: {self.output_path}")
        except Exception as e:
            print(f"❌ Error saving Excel file: {e}")
            # 如果保存失败，尝试保存到当前目录作为备份
            backup_path = "result_backup.xlsx"
            df.to_excel(backup_path, index=False)
            print(f"   -> Backup saved to project root: {backup_path}")