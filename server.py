import sys
import os
import marshal
import types

# pythonRPC目录路径
python_rpc_path = r'./pythonRPC'

def load_m(module_name, file_path):
    try:
        # 读取源代码
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        
        # 编译源代码为字节码
        compiled_code = compile(source_code, '<compiled>', 'exec')
        
        # 使用marshal序列化字节码
        marshaled_code = marshal.dumps(compiled_code)
        
        # 反序列化字节码
        code_obj = marshal.loads(marshaled_code)
        
        # 创建模块对象
        module = types.ModuleType(module_name)
        module.__file__ = '<compiled>'
        module.__loader__ = None
        
        # 执行模块代码
        exec(code_obj, module.__dict__)
        
        # 将模块添加到sys.modules中
        sys.modules[module_name] = module
        
        return module
    except Exception as e:
        print(f"Failed to load module {module_name}: {e}")
        return None

def load_ms():
    """
    加载pythonRPC目录中的所有Python模块
    """
    if not os.path.exists(python_rpc_path):
        print(f"pythonRPC path does not exist: {python_rpc_path}")
        return {}
    
    modules = {}
    
    # 遍历目录中的所有Python文件
    for filename in os.listdir(python_rpc_path):
        if filename.endswith('.py') and not filename.startswith('__'):
            module_name = filename[:-3]  # 移除.py扩展名
            file_path = os.path.join(python_rpc_path, filename)
            
            module = load_m(module_name, file_path)
            if module:
                modules[module_name] = module
    
    return modules

# 加载所有pythonRPC模块
pythonrpc_modules = load_ms()

# 从加载的模块中获取InspectServer类
InspectServer = None
if 'rpc_server' in pythonrpc_modules:
    InspectServer = getattr(pythonrpc_modules['rpc_server'], 'InspectServer', None)

if InspectServer is None:
    raise ImportError("Failed to load InspectServer class from pythonRPC modules")

import asyncio
import to_be_hook_module

# --- 全局变量 ---
ORIGINAL_GET_HTTP_REQUESTS = None
EVENT_LOOP = None
SERVER_TASK = None
PORT = 0
rpc_server = None

# === 核心的非阻塞补丁函数 ===
def patched_get_http_requests(*args, **kwargs):
    """
    这个补丁函数在每次被调用时，都会驱动 asyncio 事件循环运行所有当前待处理的任务。
    """
    global EVENT_LOOP

    if EVENT_LOOP and EVENT_LOOP.is_running():
        pass
    elif EVENT_LOOP:
        EVENT_LOOP.call_soon(EVENT_LOOP.stop)

        EVENT_LOOP.run_forever()

    if ORIGINAL_GET_HTTP_REQUESTS:
        return ORIGINAL_GET_HTTP_REQUESTS(*args, **kwargs)
    
    return None


def start_server_and_patch(port):
    """
    由C++在启动时调用一次。初始化 asyncio 服务器并应用猴子补丁。
    """
    global ORIGINAL_GET_HTTP_REQUESTS, EVENT_LOOP, SERVER_TASK, PORT, rpc_server
    
    if SERVER_TASK:
        return False

    PORT = port

    try:
        # 创建RPC服务器实例
        rpc_server = InspectServer()
        
        # 获取或创建一个新的事件循环
        EVENT_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(EVENT_LOOP)

        # 创建服务器协程
        server_coro = asyncio.start_server(rpc_server.handle_request, '0.0.0.0', port)
        
        # 将服务器协程包装成一个任务，但不启动事件循环
        SERVER_TASK = EVENT_LOOP.create_task(server_coro)

    except Exception as e:
        return False

    # 保存原始函数并应用补丁
    if hasattr(to_be_hook_module, 'to_be_hook_func') and callable(to_be_hook_module.to_be_hook_func):
        ORIGINAL_GET_HTTP_REQUESTS = to_be_hook_module.to_be_hook_func
        to_be_hook_module.to_be_hook_func = patched_get_http_requests
        return True
    else:
        # 清理已创建的任务和循环，但避免阻塞调用
        if SERVER_TASK:
            SERVER_TASK.cancel()
        if EVENT_LOOP:
            EVENT_LOOP.close()
        SERVER_TASK = None
        EVENT_LOOP = None
        return False

# === 清理函数，在C++退出前调用 ===
def cleanup_and_remove_patch():
    """
    在应用关闭时恢复原始函数并关闭服务器和事件循环。
    """
    global ORIGINAL_GET_HTTP_REQUESTS, EVENT_LOOP, SERVER_TASK, rpc_server
    
    # 恢复原始函数
    if ORIGINAL_GET_HTTP_REQUESTS and hasattr(to_be_hook_module, 'to_be_hook_func'):
        to_be_hook_module.to_be_hook_func = ORIGINAL_GET_HTTP_REQUESTS
        ORIGINAL_GET_HTTP_REQUESTS = None
    
    # 关闭 asyncio 服务器和事件循环
    if EVENT_LOOP and SERVER_TASK:
        SERVER_TASK.cancel() # 取消服务器任务
        try:
            # 运行循环直到取消操作完成
            async def shutdown_logic():
                await asyncio.sleep(0) # 给取消一个机会传播
            EVENT_LOOP.run_until_complete(shutdown_logic())
        except asyncio.CancelledError:
            pass # 这是预期的
        finally:
            EVENT_LOOP.close()
            EVENT_LOOP = None
            SERVER_TASK = None
            rpc_server = None
            
    return True

