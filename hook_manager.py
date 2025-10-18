import sys
import inspect
import types
import traceback
import gc
from id_utils import normalize_object_id
from datetime import datetime

class HMgr:
    def __init__(self):
        self.active_hooks = {}  # {hook_id: hook_info}
        self.hook_results = {}  # {hook_id: [call_records]}
        self.hook_counter = 0
        self.original_functions = {}  # 保存原始函数引用
        self.caller_cache = {}  # {hook_id: set(caller_signatures)} 用于去重
        # 调用树限制参数
        self.max_call_tree_depth = 12
        self.max_call_tree_nodes = 800
        self._call_tree_node_count = 0
        # 兄弟调用跟踪 (sibling tracking)
        self.sibling_capture_contexts = {}  # {(hook_id, thread_id, code_obj, lineno): ctx}
        self._sibling_profile_installed = False
        self._active_tracking_contexts = []  # 加速遍历当前 tracking 的 ctx 列表

    # =================== 兄弟调用跟踪支持 ===================
    def _ensure_sibling_profile(self):
        """确保设置全局 profile 分发器，仅在有 tracking 上下文时启用。"""
        import sys, threading
        if self._sibling_profile_installed:
            return
        def _dispatcher(frame, event, arg):
            if not self._active_tracking_contexts:
                return
            if event not in ('call','return'):
                return
            try:
                fid = id(frame)
                remove_list = []
                for ctx in list(self._active_tracking_contexts):
                    if ctx['state'] not in ('tracking','finishing'):
                        continue
                    # 结束判定：caller 返回（直接用 caller_frame_id 对应 frame，避免根节点不一致问题）
                    if event == 'return' and fid == ctx['caller_frame_id']:
                        # 补齐 root 结束时间
                        import time as _t
                        if ctx['root'] and ctx['root']['t_exit'] is None:
                            ctx['root']['t_exit'] = _t.perf_counter()
                        ctx['state'] = 'finished'
                        remove_list.append(ctx)
                        continue
                    if ctx['state'] != 'tracking':
                        continue
                    cache = ctx['frame_cache']
                    if fid in cache:
                        belongs = cache[fid]
                    else:
                        belongs = False
                        f2 = frame
                        root_id = ctx['caller_frame_id']
                        depth_guard = 0
                        while f2 and depth_guard < ctx['max_depth_scan']:
                            if id(f2) == root_id:
                                belongs = True
                                break
                            f2 = f2.f_back
                            depth_guard += 1
                        cache[fid] = belongs
                    if not belongs:
                        continue
                    self._handle_sibling_event(ctx, frame, event, arg)
                # 移除已完成上下文
                if remove_list:
                    for ctx in remove_list:
                        if ctx in self._active_tracking_contexts:
                            self._active_tracking_contexts.remove(ctx)
                # 如果没有活动上下文，卸载 profile
                if not self._active_tracking_contexts:
                    try:
                        sys.setprofile(None)
                        import threading as _tt
                        _tt.setprofile(None)
                    except Exception:
                        pass
                    self._sibling_profile_installed = False
            except Exception:
                pass
        sys.setprofile(_dispatcher)
        try:
            import threading as _t
            _t.setprofile(_dispatcher)
        except Exception:
            pass
        self._sibling_profile_installed = True

    def _handle_sibling_event(self, ctx, frame, event, arg):
        """对单个上下文处理call/return事件，构建调用子树。"""
        import time
        if event == 'call':
            depth = len(ctx['stack'])
            if depth >= ctx['max_depth'] or ctx['node_count'] >= ctx['max_nodes']:
                ctx['truncated'] = True
                ctx['stack'].append(None)
                return
            node = {
                'func': frame.f_code.co_name,
                'filename': frame.f_code.co_filename,
                'lineno': frame.f_code.co_firstlineno,
                't_enter': time.perf_counter(),
                't_exit': None,
                'children': [],
                'return': None
            }
            # 附加为子节点（根已在tracking启动时创建，这里永远是子节点）
            parent = ctx['stack'][-1]
            if parent is not None:
                parent['children'].append(node)
            ctx['stack'].append(node)
            ctx['node_count'] += 1
        elif event == 'return':
            if not ctx['stack']:
                return
            top = ctx['stack'].pop()
            if top is None:
                return
            import time
            top['t_exit'] = time.perf_counter()
            try:
                top['return'] = repr(arg)
            except Exception:
                top['return'] = '<unrepr>'
            # 根结束由 dispatcher 直接根据 caller_frame_id 处理

    def _arm_or_track_siblings(self, hook_id, caller_frame, enable_tracking):
        """根据当前调用点，对上下文进行arming或切换tracking。
        enable_tracking=True 表示第一次函数调用结束后开始追踪兄弟调用。"""
        import threading
        tid = threading.get_ident()
        key = (hook_id, tid, caller_frame.f_code, caller_frame.f_lineno)
        ctx = self.sibling_capture_contexts.get(key)
        if ctx is None:
            ctx = {
                'state': 'armed',
                'caller_frame_id': id(caller_frame),
                'caller_code': caller_frame.f_code,
                'stack': [],
                'root': None,
                'node_count': 0,
                'max_nodes': 2000,
                'max_depth': 40,
                'max_depth_scan': 60,
                'frame_cache': {},
                'truncated': False
            }
            self.sibling_capture_contexts[key] = ctx
            return ctx, 'armed'
        if ctx['state'] == 'armed' and enable_tracking:
            ctx['state'] = 'tracking'
            # 创建 caller 根节点（进入 tracking 的时间点）
            import time as _t
            ctx['root'] = {
                'func': ctx['caller_code'].co_name,
                'filename': ctx['caller_code'].co_filename,
                'lineno': ctx['caller_code'].co_firstlineno,
                't_enter': _t.perf_counter(),
                't_exit': None,
                'children': [],
                'return': None
            }
            ctx['stack'] = [ctx['root']]
            if ctx not in self._active_tracking_contexts:
                self._active_tracking_contexts.append(ctx)
            self._ensure_sibling_profile()
            return ctx, 'tracking'
        return ctx, ctx['state']

    def _snapshot_sibling_context(self, ctx, shallow=True):
        """生成当前兄弟调用树的浅快照（不修改原结构）。"""
        def clone(node):
            if node is None: return None
            c = {
                'func': node['func'],
                'filename': node['filename'],
                'lineno': node['lineno'],
                't_enter': node['t_enter'],
                't_exit': node['t_exit'],
                'return': node['return'],
            }
            if not shallow:
                c['children'] = [clone(ch) for ch in node.get('children', [])]
            else:
                c['children'] = len(node.get('children', []))
            return c
        snap = {
            'state': ctx['state'],
            'truncated': ctx.get('truncated', False),
            'node_count': ctx.get('node_count', 0),
            'root': clone(ctx['root'])
        }
        return snap
    
    def create_hook(self, hook_data):
        """创建Hook"""
        try:
            module_name = hook_data.get('module')
            function_name = hook_data.get('function')
            hook_type = hook_data.get('type', 'log')  # log, modify, block
            custom_code = hook_data.get('code', '')  # 自定义代码
            object_id = hook_data.get('object_id')  # 对象ID，用于对象方法HOOK (字符串形式)
            record_caller = hook_data.get('record_caller', True)  # 是否记录调用者
            unique_caller_only = hook_data.get('unique_caller_only', False)  # 是否每个调用者只记录一次
            record_call_tree = hook_data.get('record_call_tree', False)  # 是否记录调用树
            record_caller_siblings = hook_data.get('record_caller_siblings', False)  # 是否记录首次调用之后的caller作用域兄弟调用
            
            if not module_name or not function_name:
                return {'error': 'Module and function name are required'}
            
            # 处理对象实例方法HOOK
            if module_name == 'object' and object_id is not None:
                ok, oid = normalize_object_id(object_id)
                if not ok:
                    return {'error': f'Invalid object_id: {object_id}', 'detail': oid}
                return self._create_object_hook(str(oid), function_name, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree, record_caller_siblings)
            
            # 处理类方法HOOK (例如: entities.Avatar.apply_non_pc_config_data)
            if '.' in function_name:
                return self._create_class_method_hook(module_name, function_name, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree, record_caller_siblings)
            
            # 处理模块函数HOOK
            # 检查模块是否存在
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
            
            module_obj = sys.modules[module_name]
            
            # 检查函数是否存在
            if not hasattr(module_obj, function_name):
                return {'error': f'Function {function_name} not found in module {module_name}'}
            
            original_func = getattr(module_obj, function_name)
            
            # 检查是否已经被Hook
            hook_key = f"{module_name}.{function_name}"
            if hook_key in self.original_functions:
                return {'error': f'Function {hook_key} is already hooked'}
            
            # 生成Hook ID
            self.hook_counter += 1
            hook_id = str(self.hook_counter)
            
            # 保存原始函数
            self.original_functions[hook_key] = original_func
            
            # 创建Hook函数
            def create_hook_wrapper(orig_func, h_id, h_type, h_code, rec_caller, unique_only, rec_tree, rec_siblings):
                def hook_wrapper(*args, **kwargs):
                    # 获取调用链信息
                    caller_info = None
                    caller_signature = None
                    if rec_caller:
                        caller_info = self._get_caller_chain()
                        caller_signature = self._get_caller_signature(caller_info)
                        
                        # 如果启用了去重且该调用者已记录过，则直接透传
                        if unique_only and h_id in self.caller_cache:
                            if caller_signature in self.caller_cache[h_id]:
                                return orig_func(*args, **kwargs)
                    
                    call_info = {
                        'timestamp': datetime.now().isoformat(),
                        'args': [repr(arg) for arg in args],
                        'kwargs': {k: repr(v) for k, v in kwargs.items()},
                        'hook_id': h_id,
                        'caller_chain': caller_info if rec_caller else None
                    }
                    # 兄弟调用跟踪：在函数调用开始时执行 arming/ snapshot
                    ctx = None
                    initial_state = None
                    if rec_siblings:
                        import sys as _sys
                        caller_frame = _sys._getframe(1)
                        ctx, initial_state = self._arm_or_track_siblings(h_id, caller_frame, enable_tracking=False)
                        if ctx and ctx.get('state') == 'tracking':
                            # 处于tracking阶段，采集快照（浅）
                            call_info['caller_siblings_snapshot'] = self._snapshot_sibling_context(ctx, shallow=True)

                    error_raised = False
                    try:
                        if h_type == 'block':
                            call_info['blocked'] = True
                            call_info['result'] = 'Function call blocked by hook'
                            return None
                        elif h_type == 'modify' and h_code:
                            exec_globals = {
                                'args': list(args),
                                'kwargs': kwargs,
                                'original_function': orig_func,
                                '__builtins__': __builtins__
                            }
                            try:
                                exec(h_code, exec_globals)
                            except Exception as e_exec:
                                call_info['error'] = f'Hook execution error: {e_exec}'
                            modified_args = exec_globals.get('args', args)
                            modified_kwargs = exec_globals.get('kwargs', kwargs)
                            result = orig_func(*modified_args, **modified_kwargs)
                            call_info['modified'] = True
                            call_info['result'] = repr(result)
                            return result
                        else:
                            if rec_tree:
                                result, tree = self._capture_call_subtree(orig_func, args, kwargs)
                                call_info['result'] = repr(result)
                                call_info['call_tree'] = tree
                                return result
                            else:
                                result = orig_func(*args, **kwargs)
                                call_info['result'] = repr(result)
                                return result
                    except Exception as e:
                        error_raised = True
                        call_info['error'] = str(e)
                        call_info['traceback'] = traceback.format_exc()
                        raise
                    finally:
                        # 如果之前是 armed 状态，本次调用结束后切换为 tracking
                        if rec_siblings and ctx and ctx.get('state') == 'armed':
                            # 再次使用同一个caller_frame启用tracking
                            try:
                                self._arm_or_track_siblings(h_id, caller_frame, enable_tracking=True)
                            except Exception:
                                pass
                        # 记录结果
                        self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                        if error_raised:
                            # 异常已经抛出，让其向上继续
                            pass
                
                return hook_wrapper
            
            # 创建并应用Hook
            hook_wrapper = create_hook_wrapper(original_func, hook_id, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree, record_caller_siblings)
            setattr(module_obj, function_name, hook_wrapper)
            
            # 保存Hook信息
            hook_info = {
                'id': hook_id,
                'module': module_name,
                'function': function_name,
                'type': hook_type,
                'code': custom_code,
                'record_caller': record_caller,
                'unique_caller_only': unique_caller_only,
                'record_call_tree': record_call_tree,
                'record_caller_siblings': record_caller_siblings,
                'created_at': datetime.now().isoformat(),
                'call_count': 0
            }
            
            self.active_hooks[hook_id] = hook_info
            self.hook_results[hook_id] = []
            
            # 初始化调用者缓存
            if unique_caller_only:
                self.caller_cache[hook_id] = set()
            
            return {'success': True, 'hook_id': hook_id, 'hook_info': hook_info}
            
        except Exception as e:
            return {'error': str(e)}
    
    def _create_class_method_hook(self, module_name, function_path, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree=False, record_caller_siblings=False):
        """创建类方法Hook (例如: Avatar.apply_non_pc_config_data)"""
        try:
            # 解析类方法路径
            path_parts = function_path.split('.')
            if len(path_parts) < 2:
                return {'error': 'Invalid class method path format'}
            
            class_name = path_parts[0]
            method_name = '.'.join(path_parts[1:])  # 支持嵌套方法
            
            # 检查模块是否存在
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
            
            module_obj = sys.modules[module_name]
            
            # 检查类是否存在
            if not hasattr(module_obj, class_name):
                return {'error': f'Class {class_name} not found in module {module_name}'}
            
            class_obj = getattr(module_obj, class_name)
            
            # 检查是否是类
            if not inspect.isclass(class_obj):
                return {'error': f'{class_name} is not a class'}
            
            # 检查方法是否存在
            if not hasattr(class_obj, method_name):
                return {'error': f'Method {method_name} not found in class {class_name}'}
            
            original_method = getattr(class_obj, method_name)
            
            # 检查是否已经被Hook
            hook_key = f"{module_name}.{class_name}.{method_name}"
            if hook_key in self.original_functions:
                return {'error': f'Method {hook_key} is already hooked'}
            
            # 生成Hook ID
            self.hook_counter += 1
            hook_id = str(self.hook_counter)
            
            # 保存原始方法
            self.original_functions[hook_key] = original_method
            
            # 创建Hook方法
            def create_method_hook_wrapper(orig_method, h_id, h_type, h_code, rec_caller, unique_only, rec_tree, rec_siblings):
                def method_hook_wrapper(*args, **kwargs):
                    # 获取调用链信息
                    caller_info = None
                    caller_signature = None
                    if rec_caller:
                        caller_info = self._get_caller_chain()
                        caller_signature = self._get_caller_signature(caller_info)
                        
                        # 如果启用了去重且该调用者已记录过，则直接透传
                        if unique_only and h_id in self.caller_cache:
                            if caller_signature in self.caller_cache[h_id]:
                                return orig_method(*args, **kwargs)
                    
                    call_info = {
                        'timestamp': datetime.now().isoformat(),
                        'args': [repr(arg) for arg in args],
                        'kwargs': {k: repr(v) for k, v in kwargs.items()},
                        'hook_id': h_id,
                        'caller_chain': caller_info if rec_caller else None
                    }
                    # 兄弟调用跟踪 arming / snapshot
                    ctx = None
                    if rec_siblings:
                        import sys as _sys
                        caller_frame = _sys._getframe(1)
                        ctx, _st = self._arm_or_track_siblings(h_id, caller_frame, enable_tracking=False)
                        if ctx and ctx.get('state') == 'tracking':
                            call_info['caller_siblings_snapshot'] = self._snapshot_sibling_context(ctx, shallow=True)
                    
                    try:
                        if h_type == 'block':
                            # 阻塞调用
                            call_info['result'] = 'BLOCKED'
                            call_info['blocked'] = True
                            self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                            return None
                        elif h_type == 'modify' and h_code:
                            # 修改调用
                            local_vars = {
                                'args': args,
                                'kwargs': kwargs,
                                'original_method': orig_method
                            }
                            exec(h_code, globals(), local_vars)
                            result = local_vars.get('result', orig_method(*args, **kwargs))
                            call_info['result'] = repr(result)
                            call_info['modified'] = True
                            self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                            return result
                        else:
                            # 记录调用
                            if rec_tree:
                                result, tree = self._capture_call_subtree(orig_method, args, kwargs)
                                call_info['result'] = repr(result)
                                call_info['call_tree'] = tree
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                return result
                            else:
                                result = orig_method(*args, **kwargs)
                                call_info['result'] = repr(result)
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                return result
                    except Exception as e:
                        call_info['error'] = str(e)
                        call_info['traceback'] = traceback.format_exc()
                        self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                        raise
                    finally:
                        if rec_siblings and ctx and ctx.get('state') == 'armed':
                            try:
                                self._arm_or_track_siblings(h_id, caller_frame, enable_tracking=True)
                            except Exception:
                                pass
                
                return method_hook_wrapper
            
            # 创建Hook包装器
            hook_wrapper = create_method_hook_wrapper(original_method, hook_id, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree, record_caller_siblings)
            
            # 应用Hook
            setattr(class_obj, method_name, hook_wrapper)
            
            # 保存Hook信息
            self.active_hooks[hook_id] = {
                'id': hook_id,
                'module': module_name,
                'class': class_name,
                'function': method_name,
                'type': hook_type,
                'code': custom_code,
                'created_at': datetime.now().isoformat(),
                'record_caller': record_caller,
                'unique_caller_only': unique_caller_only,
                'record_call_tree': record_call_tree,
                'record_caller_siblings': record_caller_siblings,
                'call_count': 0
            }
            
            # 初始化结果存储
            self.hook_results[hook_id] = []
            
            # 初始化调用者缓存
            if unique_caller_only:
                self.caller_cache[hook_id] = set()
            
            return {
                'success': True,
                'hook_id': hook_id,
                'message': f'Successfully hooked {hook_key}'
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _create_object_hook(self, object_id, method_name, hook_type, custom_code, record_caller, unique_caller_only, record_call_tree=False, record_caller_siblings=False):
        """创建对象实例方法Hook"""
        try:
            # 通过gc查找对象
            target_obj = None
            ok, oid = normalize_object_id(object_id)
            if not ok:
                return {'error': f'Invalid object_id: {object_id}', 'detail': oid}
            for obj in gc.get_objects():
                if id(obj) == oid:
                    target_obj = obj
                    break
                    
            if target_obj is None:
                return {'error': f'Object with ID {object_id} not found'}
                
            # 检查方法是否存在
            if not hasattr(target_obj, method_name):
                return {'error': f'Method {method_name} not found in object {object_id}'}
                
            original_method = getattr(target_obj, method_name)
            
            # 检查是否可调用
            if not callable(original_method):
                return {'error': f'{method_name} is not callable'}
            
            # 检查是否已经被Hook
            hook_key = f"object_{object_id}.{method_name}"
            if hook_key in self.original_functions:
                return {'error': f'Method {hook_key} is already hooked'}
            
            # 生成Hook ID
            self.hook_counter += 1
            hook_id = str(self.hook_counter)
            
            # 保存原始方法
            self.original_functions[hook_key] = original_method
            
            # 创建Hook函数
            def create_object_hook_wrapper(orig_method, h_id, h_type, h_code, obj_id, rec_caller, unique_only, rec_tree, rec_siblings):
                def hook_wrapper(*args, **kwargs):
                    # 获取调用链信息
                    caller_info = None
                    caller_signature = None
                    if rec_caller:
                        caller_info = self._get_caller_chain()
                        caller_signature = self._get_caller_signature(caller_info)
                        
                        # 如果启用了去重且该调用者已记录过，则直接透传
                        if unique_only and h_id in self.caller_cache:
                            if caller_signature in self.caller_cache[h_id]:
                                return orig_method(*args, **kwargs)
                    
                    call_info = {
                        'timestamp': datetime.now().isoformat(),
                        'object_id': obj_id,
                        'method_name': method_name,
                        'args': [repr(arg) for arg in args],
                        'kwargs': {k: repr(v) for k, v in kwargs.items()},
                        'hook_id': h_id,
                        'caller_chain': caller_info if rec_caller else None
                    }
                    # 兄弟调用跟踪 arming / snapshot
                    ctx = None
                    if rec_siblings:
                        import sys as _sys
                        caller_frame = _sys._getframe(1)
                        ctx, _st = self._arm_or_track_siblings(h_id, caller_frame, enable_tracking=False)
                        if ctx and ctx.get('state') == 'tracking':
                            call_info['caller_siblings_snapshot'] = self._snapshot_sibling_context(ctx, shallow=True)
                    
                    try:
                        if h_type == 'block':
                            # 阻止方法执行
                            call_info['blocked'] = True
                            call_info['result'] = 'Method call blocked by hook'
                            self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                            return None
                        
                        elif h_type == 'modify' and h_code:
                            # 执行自定义代码修改参数或行为
                            try:
                                # 创建执行环境
                                exec_globals = {
                                    'args': list(args),
                                    'kwargs': kwargs,
                                    'original_method': orig_method,
                                    'target_object': target_obj,
                                    '__builtins__': __builtins__
                                }
                                
                                # 执行自定义代码
                                exec(h_code, exec_globals)
                                
                                # 获取修改后的参数
                                modified_args = exec_globals.get('args', args)
                                modified_kwargs = exec_globals.get('kwargs', kwargs)
                                
                                # 调用原始方法
                                result = orig_method(*modified_args, **modified_kwargs)
                                
                                call_info['modified'] = True
                                call_info['result'] = repr(result)
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                
                                return result
                                
                            except Exception as e:
                                call_info['error'] = f'Hook execution error: {str(e)}'
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                # 如果Hook执行失败，继续执行原始方法
                                result = orig_method(*args, **kwargs)
                                return result
                        
                        else:
                            # 默认log模式，记录调用但不修改
                            if rec_tree:
                                result, tree = self._capture_call_subtree(orig_method, args, kwargs)
                                call_info['result'] = repr(result)
                                call_info['call_tree'] = tree
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                return result
                            else:
                                result = orig_method(*args, **kwargs)
                                call_info['result'] = repr(result)
                                self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                                return result
                            
                    except Exception as e:
                        call_info['error'] = str(e)
                        call_info['traceback'] = traceback.format_exc()
                        self._add_hook_result(h_id, call_info, caller_signature, unique_only)
                        raise
                
                return hook_wrapper
            
            # 创建并应用Hook
            hook_wrapper = create_object_hook_wrapper(original_method, hook_id, hook_type, custom_code, object_id, record_caller, unique_caller_only, record_call_tree, record_caller_siblings)
            setattr(target_obj, method_name, hook_wrapper)
            
            # 保存Hook信息
            hook_info = {
                'id': hook_id,
                'module': 'object',
                'object_id': object_id,
                'function': method_name,
                'type': hook_type,
                'code': custom_code,
                'record_caller': record_caller,
                'unique_caller_only': unique_caller_only,
                'record_call_tree': record_call_tree,
                'record_caller_siblings': record_caller_siblings,
                'created_at': datetime.now().isoformat(),
                'call_count': 0
            }
            
            self.active_hooks[hook_id] = hook_info
            self.hook_results[hook_id] = []
            
            # 初始化调用者缓存
            if unique_caller_only:
                self.caller_cache[hook_id] = set()
            
            return {'success': True, 'hook_id': hook_id, 'hook_info': hook_info}
            
        except Exception as e:
            return {'error': str(e)}
    
    def remove_hook(self, hook_id):
        """移除Hook"""
        try:
            if hook_id not in self.active_hooks:
                return {'error': 'Hook not found'}
            
            hook_info = self.active_hooks[hook_id]
            module_name = hook_info['module']
            function_name = hook_info['function']
            
            # 处理对象方法Hook
            if module_name == 'object' and 'object_id' in hook_info:
                object_id = hook_info['object_id']
                ok, oid = normalize_object_id(object_id)
                if not ok:
                    return {'error': f'Invalid object_id: {object_id}', 'detail': oid}
                hook_key = f"object_{object_id}.{function_name}"
                
                # 恢复原始方法
                if hook_key in self.original_functions:
                    # 通过gc查找对象
                    target_obj = None
                    for obj in gc.get_objects():
                        if id(obj) == oid:
                            target_obj = obj
                            break
                    
                    if target_obj is not None:
                        setattr(target_obj, function_name, self.original_functions[hook_key])
                    
                    del self.original_functions[hook_key]
            else:
                # 处理模块函数Hook
                hook_key = f"{module_name}.{function_name}"
                
                # 恢复原始函数
                if hook_key in self.original_functions:
                    module_obj = sys.modules[module_name]
                    setattr(module_obj, function_name, self.original_functions[hook_key])
                    del self.original_functions[hook_key]
            
            # 清理Hook数据
            del self.active_hooks[hook_id]
            if hook_id in self.hook_results:
                del self.hook_results[hook_id]
            if hook_id in self.caller_cache:
                del self.caller_cache[hook_id]
            
            return {'success': True, 'message': f'Hook {hook_id} removed'}
            
        except Exception as e:
            return {'error': str(e)}
    
    def get_hooks(self):
        """获取所有Hook"""
        try:
            hooks_with_stats = {}
            for hook_id, hook_info in self.active_hooks.items():
                hook_with_stats = hook_info.copy()
                hook_with_stats['call_count'] = len(self.hook_results.get(hook_id, []))
                hooks_with_stats[hook_id] = hook_with_stats
            
            return {'hooks': hooks_with_stats}
        except Exception as e:
            return {'error': str(e)}
    
    def get_hook_results(self, hook_id, page=1, page_size=20):
        """获取Hook调用结果"""
        try:
            if hook_id not in self.active_hooks:
                return {'error': 'Hook not found'}
            
            results = self.hook_results.get(hook_id, [])
            total_count = len(results)
            total_pages = (total_count + page_size - 1) // page_size
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            
            # 获取当前页的结果（最新的在前面）
            page_results = list(reversed(results))[start_index:end_index]
            
            return {
                'results': page_results,
                'pagination': {
                    'current_page': page,
                    'page_size': page_size,
                    'total_count': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def clear_hook_results(self, hook_id):
        """清空Hook调用结果"""
        try:
            if hook_id not in self.active_hooks:
                return {'error': 'Hook not found'}
            
            self.hook_results[hook_id] = []
            return {'success': True, 'message': f'Hook {hook_id} results cleared'}
        except Exception as e:
            return {'error': str(e)}
    
    def _add_hook_result(self, hook_id, call_info, caller_signature=None, unique_only=False):
        """添加Hook调用结果"""
        if hook_id not in self.hook_results:
            self.hook_results[hook_id] = []
        
        # 如果启用了去重，将调用者签名添加到缓存
        if unique_only and caller_signature and hook_id in self.caller_cache:
            self.caller_cache[hook_id].add(caller_signature)
        
        self.hook_results[hook_id].append(call_info)
        
        # 更新调用计数
        if hook_id in self.active_hooks:
            self.active_hooks[hook_id]['call_count'] += 1
        
        # 限制结果数量，避免内存溢出
        if len(self.hook_results[hook_id]) > 1000:
            self.hook_results[hook_id] = self.hook_results[hook_id][-500:]
    
    def _get_caller_chain(self, max_depth=10):
        """获取调用链信息"""
        caller_chain = []
        frame = inspect.currentframe()
        
        try:
            # 跳过当前方法和hook_wrapper
            for _ in range(3):
                if frame:
                    frame = frame.f_back
            
            depth = 0
            while frame and depth < max_depth:
                frame_info = {
                    'filename': frame.f_code.co_filename,
                    'function': frame.f_code.co_name,
                    'lineno': frame.f_lineno,
                    'code_context': None
                }
                
                # 尝试获取代码上下文
                try:
                    lines, start_line = inspect.findsource(frame)
                    current_line = frame.f_lineno - start_line
                    if 0 <= current_line < len(lines):
                        frame_info['code_context'] = lines[current_line].strip()
                except:
                    pass
                
                caller_chain.append(frame_info)
                frame = frame.f_back
                depth += 1
                
        except Exception as e:
            # 如果获取调用链失败，至少记录错误信息
            caller_chain.append({'error': f'Failed to get caller chain: {str(e)}'})
        finally:
            del frame  # 避免循环引用
        
        return caller_chain
    
    def _get_caller_signature(self, caller_chain):
        """生成调用者签名用于去重"""
        if not caller_chain:
            return 'unknown_caller'
        
        # 使用前3个调用帧生成签名
        signature_parts = []
        for frame_info in caller_chain[:3]:
            if 'error' in frame_info:
                signature_parts.append('error_frame')
            else:
                filename = frame_info.get('filename', 'unknown')
                function = frame_info.get('function', 'unknown')
                lineno = frame_info.get('lineno', 0)
                signature_parts.append(f"{filename}:{function}:{lineno}")
        
        return '|'.join(signature_parts)
    
    def cleanup_all_hooks(self):
        """清理所有Hook"""
        try:
            hook_ids = list(self.active_hooks.keys())
            for hook_id in hook_ids:
                self.remove_hook(hook_id)
            
            return {'success': True, 'message': f'Removed {len(hook_ids)} hooks'}
        except Exception as e:
            return {'error': str(e)}

    # ============ 调用树采集 ============
    def _capture_call_subtree(self, target_func, args, kwargs):
        """使用临时profile捕获目标函数内部的调用嵌套结构。
        仅关注从进入 target_func 到其返回期间发生的调用，不回溯其之前已执行的兄弟调用；也不捕获函数返回后外层继续执行的额外分支（那已不在函数执行窗口）。"""
        import sys as _sys, threading
        self._call_tree_node_count = 0
        main_thread_ident = threading.get_ident()
        code_obj = getattr(target_func, '__code__', None)
        root_node = {
            'function': getattr(target_func, '__name__', '<lambda>'),
            'filename': code_obj.co_filename if code_obj else None,
            'lineno': code_obj.co_firstlineno if code_obj else None,
            'children': [],
            'return': None,
        }

        # ========== 内建 / C 扩展函数（无 __code__ 或 code_obj None）处理 ==========
        # 这类函数不会产生 Python 级别的内部 call 事件（内部在 C 层），无法构建子调用树。
        # 直接执行函数，记录耗时与返回值，标记 native=True，避免误标 incomplete。
        if code_obj is None:
            import time as _t
            t_enter = _t.perf_counter()
            try:
                result = target_func(*args, **kwargs)
            except Exception as e:
                # 依旧返回 root 节点，标明异常
                try:
                    root_node['return'] = f'<error {e}>'
                except Exception:
                    root_node['return'] = '<error>'
                root_node['native'] = True
                root_node['t_enter'] = t_enter
                root_node['t_exit'] = _t.perf_counter()
                root_node['exception'] = traceback.format_exc()
                return None, root_node
            else:
                try:
                    root_node['return'] = repr(result)
                except Exception:
                    root_node['return'] = '<unreprable>'
                root_node['native'] = True
                root_node['t_enter'] = t_enter
                root_node['t_exit'] = _t.perf_counter()
                return result, root_node

        stack = []  # 保存 (frame, node, depth)
        target_code = code_obj
        capturing = {'active': False, 'finished': False}

        def _too_big():
            return self._call_tree_node_count >= self.max_call_tree_nodes

        def _profile(frame, event, arg):
            # 只监控主线程
            if threading.get_ident() != main_thread_ident:
                return
            if capturing['finished']:
                return
            try:
                if event == 'call':
                    # 进入某个函数
                    code = frame.f_code
                    # 激活起点：第一次遇到 target_func 的 code（外层包裹函数触发 call 事件）
                    if not capturing['active']:
                        if target_code is not None and code is target_code:
                            capturing['active'] = True
                            stack.append((frame, root_node, 0))
                        return
                    # 已在捕获区域内
                    if not stack:
                        return
                    parent_depth = stack[-1][2]
                    depth = parent_depth + 1
                    if depth > self.max_call_tree_depth or _too_big():
                        return
                    node = {
                        'function': code.co_name,
                        'filename': code.co_filename,
                        'lineno': code.co_firstlineno,
                        'children': [],
                        'return': None,
                    }
                    stack[-1][1]['children'].append(node)
                    stack.append((frame, node, depth))
                    self._call_tree_node_count += 1
                elif event == 'return':
                    if not capturing['active']:
                        return
                    if not stack:
                        return
                    frame_top, node_top, _depth = stack[-1]
                    if frame is frame_top:
                        # 记录返回值表示
                        try:
                            node_top['return'] = repr(arg)
                        except Exception:
                            node_top['return'] = '<unreprable>'
                        stack.pop()
                        if not stack:  # 根函数返回
                            capturing['finished'] = True
            except Exception:
                pass

        old_profile = _sys.getprofile()
        try:
            _sys.setprofile(_profile)
            result = target_func(*args, **kwargs)
            return result, root_node
        finally:
            _sys.setprofile(old_profile)
            # 只有在确实进入过 target 函数且未完整返回时，才标记 incomplete
            if capturing['active'] and not capturing['finished']:
                root_node['incomplete'] = True