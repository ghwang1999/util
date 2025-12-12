import os
import requests
import json
import urllib3
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage

# 禁用内网HTTPS证书警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMGenerator:
    def __init__(self, config):
        self.config = config
        self.mode = config['llm_config']['mode']
        
        # 预定义 Prompt 模板
        self.prompt_template_str = """你是一个专业的助手。请根据以下参考资料回答问题。如果资料中没有答案，请说明无法回答。
            
参考资料：
{context}

问题：{question}

答案："""
        
        if self.mode == 'external':
            print(f"[LLM] Mode: External ({config['llm_config']['external']['model_name']})")
            self._init_external_llm()
        elif self.mode == 'internal':
            print(f"[LLM] Mode: Internal ({config['llm_config']['internal']['model_name']})")
            # 内网模式不需要初始化LangChain对象，直接走Requests
        else:
            raise ValueError(f"Unknown LLM mode: {self.mode}")

    def _init_external_llm(self):
        """初始化标准 OpenAI 接口"""
        ext_conf = self.config['llm_config']['external']
        self.llm = ChatOpenAI(
            openai_api_base=ext_conf['api_base'],
            openai_api_key=ext_conf['api_key'],
            model_name=ext_conf['model_name'],
            temperature=0.1
        )
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question"],
            template=self.prompt_template_str
        )

    def generate_answer(self, query, retrieved_docs):
        """统一生成入口"""
        # 1. 拼接上下文
        context_str = "\n\n".join([f"片段 {i+1}: {doc.page_content}" for i, doc in enumerate(retrieved_docs)])
        
        # 2. 根据模式分发
        if self.mode == 'external':
            return self._generate_external(context_str, query)
        else:
            return self._generate_internal(context_str, query)

    def _generate_external(self, context, query):
        """调用标准 LangChain 接口"""
        prompt = self.prompt_template.format(context=context, question=query)
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            return f"Error (External): {e}"

    def _generate_internal(self, context, query):
        """调用内网 GTSLLM 接口 (Requests)"""
        int_conf = self.config['llm_config']['internal']
        
        # 构建完整的 Prompt 内容
        full_user_prompt = self.prompt_template_str.format(context=context, question=query)
        
        # 设置环境变量确保不走代理
        # 注意：这里临时设置环境变量，可能会影响多线程，但在目前单进程逻辑下是安全的
        os.environ['no_proxy'] = int_conf.get('no_proxy_ips', '*')
        os.environ['NO_PROXY'] = int_conf.get('no_proxy_ips', '*')
        
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": int_conf['model_name'],
            "messages": [
                {"role": "system", "content": "你是一个乐于助人的AI助手。"},
                {"role": "user", "content": full_user_prompt}
            ],
            "temperature": 0.1, # RAG 任务建议低温度
            "max_tokens": 2048,
            "stream": True
        }

        full_response_content = ""
        print(f" -> Calling Internal API...", end=" ", flush=True)

        try:
            # 发起请求
            response = requests.post(
                int_conf['api_url'], 
                headers=headers, 
                json=payload, 
                verify=False, # 忽略 SSL 验证
                timeout=int_conf['timeout'], 
                stream=True
            )
            response.raise_for_status()

            # 处理流式响应
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        json_str = decoded_line[len('data: '):]
                        
                        if json_str.strip() == '[DONE]':
                            break
                            
                        try:
                            data = json.loads(json_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content_chunk = delta.get("content", "")
                            
                            if content_chunk:
                                # 这里我们不在控制台打印每个字，避免刷屏，只收集
                                full_response_content += content_chunk
                        except json.JSONDecodeError:
                            continue
            
            print("Done.")
            return full_response_content

        except Exception as e:
            print(f"\n[Error] Internal API call failed: {e}")
            return f"Error generating answer: {e}"