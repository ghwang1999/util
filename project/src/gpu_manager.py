import threading
import time
import torch
import logging

class GpuAdaptiveManager:
    def __init__(self, config):
        self.enabled = config['adaptive_gpu']['enabled']
        # 初始最大并发数 = 配置文件里的 concurrency
        self.max_capacity = config['execution']['concurrency']
        self.current_capacity = self.max_capacity
        self.min_capacity = config['adaptive_gpu'].get('min_concurrency', 1)
        self.step_size = config['adaptive_gpu'].get('step_size', 2)
        self.cool_down = config['adaptive_gpu'].get('cool_down', 5)
        
        # 信号量：控制同时进入 GPU 任务的线程数
        self.semaphore = threading.Semaphore(self.max_capacity)
        # 锁：防止多个线程同时修改 current_capacity
        self.lock = threading.Lock()

    def run_with_protection(self, func, *args, **kwargs):
        """
        包装执行函数，提供 OOM 自动降级保护
        """
        if not self.enabled or not torch.cuda.is_available():
            # 如果没开启保护或没GPU，直接运行
            return func(*args, **kwargs)

        while True:
            # 1. 申请令牌
            self.semaphore.acquire()
            
            try:
                # 2. 执行 GPU 任务
                return func(*args, **kwargs)
                
            except torch.cuda.OutOfMemoryError:
                # 3. 捕获 OOM 异常
                print(f"\n[GPU WARNING] OOM Detected! Initiating fallback protocol...")
                
                # 释放显存
                torch.cuda.empty_cache()
                
                # 触发降级逻辑
                self._shrink_capacity()
                
                # 4. 暂停一会，让显存彻底释放，然后 continue 循环重试
                time.sleep(self.cool_down)
                continue
                
            except Exception as e:
                # 其他异常直接抛出，不重试
                raise e
            finally:
                # 5. 任务结束（无论成功失败），释放令牌
                self.semaphore.release()

    def _shrink_capacity(self):
        """降低并发容量"""
        with self.lock:
            # 如果已经降到最低，就不再降了，只能硬抗或报错
            if self.current_capacity <= self.min_capacity:
                print(f"[GPU ALERT] Capacity reached minimum ({self.min_capacity}). Retrying without shrinking.")
                return

            # 计算需要减少的数量
            new_capacity = max(self.min_capacity, self.current_capacity - self.step_size)
            reduce_amount = self.current_capacity - new_capacity
            
            print(f"[GPU ADAPTIVE] Reducing GPU concurrency from {self.current_capacity} to {new_capacity}.")
            self.current_capacity = new_capacity
            
            # 关键：通过"空占"信号量来减少可用名额
            # 我们在后台启动一个线程去永久占用 reduce_amount 个信号量，或者直接在这里 acquire 不释放
            # 简单的做法：主线程直接 acquire 掉 N 个令牌，并且永远不 release
            # 注意：acquire 可能会阻塞，这里使用非阻塞尝试，或者更简单的逻辑：
            # 修正：直接修改逻辑，下次 acquire 时更难拿到？
            
            # 更好的实现方法：
            # 由于 Semaphore 无法动态调整上限，我们采用 "Acquire without Release" 的策略来降低总数。
            for _ in range(reduce_amount):
                # block=False 防止在全部被占用时死锁，虽然在这个逻辑点通常能拿到
                # 如果拿不到，说明都忙，反正总数限制目的是达到的
                self.semaphore.acquire(blocking=False)