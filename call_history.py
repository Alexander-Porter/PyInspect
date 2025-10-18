import sys
import inspect
import gc
from datetime import datetime

class CHMgr:
    def __init__(self):
        self.call_history = []  # 存储所有函数调用历史
        self.history_counter = 0
    
    def add_to_call_history(self, call_type, module_name, function_name, args, kwargs, result=None, error=None):
        """添加调用历史记录"""
        try:
            self.history_counter += 1
            
            # 限制参数和结果的长度
            safe_args = []
            for arg in args:
                try:
                    safe_args.append(repr(arg))
                except:
                    safe_args.append('<unpresentable>')
            
            safe_kwargs = {}
            for key, value in kwargs.items():
                try:
                    safe_kwargs[key] = repr(value)
                except:
                    safe_kwargs[key] = '<unpresentable>'
            
            safe_result = None
            if result is not None:
                try:
                    if isinstance(result, dict) and 'type' in result and 'repr' in result:
                        safe_result = result
                    else:
                        safe_result = {
                            'type': type(result).__name__,
                            'repr': repr(result)
                        }
                except:
                    safe_result = {'type': 'unknown', 'repr': '<unpresentable>'}
            
            history_record = {
                'id': self.history_counter,
                'timestamp': datetime.now().isoformat(),
                'type': call_type,
                'module': module_name,
                'function': function_name,
                'args': safe_args,
                'kwargs': safe_kwargs,
                'result': safe_result,
                'error': error
            }
            
            self.call_history.append(history_record)
            
            # 限制历史记录数量，避免内存溢出
            if len(self.call_history) > 10000:
                self.call_history = self.call_history[-5000:]
                
        except Exception as e:
            # 记录历史失败不应该影响主要功能
            pass
    
    def get_call_history(self, page=1, page_size=20):
        """获取调用历史，支持分页"""
        try:
            # 计算分页
            total_count = len(self.call_history)
            total_pages = (total_count + page_size - 1) // page_size
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            
            # 获取当前页的历史记录（最新的在前面）
            page_history = list(reversed(self.call_history))[start_index:end_index]
            
            return {
                'history': page_history,
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
    
    def replay_call(self, history_id):
        """重放历史调用"""
        try:
            # 查找历史记录
            target_record = None
            for record in self.call_history:
                if record['id'] == history_id:
                    target_record = record
                    break
            
            if not target_record:
                return {'error': 'History record not found'}
            
            call_type = target_record['type']
            module_name = target_record['module']
            function_name = target_record['function']
            args = target_record['args']
            kwargs = target_record['kwargs']
            
            if call_type == 'function_call':
                return self._replay_function_call(module_name, function_name, args, kwargs)
            elif call_type == 'object_method':
                return self._replay_object_method(module_name, function_name, args, kwargs)
            else:
                return {'error': f'Unsupported call type: {call_type}'}
                
        except Exception as e:
            return {'error': str(e)}
    
    def _replay_function_call(self, module_name, function_name, args, kwargs):
        """重放函数调用"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
            
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, function_name):
                return {'error': f'Function {function_name} not found in module {module_name}'}
            
            func = getattr(module_obj, function_name)
            if not callable(func):
                return {'error': f'{function_name} is not callable'}
            
            # 尝试重新构造参数（这里简化处理，实际可能需要更复杂的反序列化）
            try:
                # 注意：这里的args和kwargs是字符串表示，需要谨慎处理
                # 为了安全，我们不执行eval，而是提供重放信息
                result = {
                    'success': True,
                    'message': 'Replay information prepared',
                    'replay_info': {
                        'module': module_name,
                        'function': function_name,
                        'args_repr': args,
                        'kwargs_repr': kwargs,
                        'note': 'Arguments are string representations. Manual reconstruction may be needed.'
                    }
                }
                
                # 添加到调用历史
                self.add_to_call_history('replay', module_name, function_name, [], {}, result)
                
                return result
                
            except Exception as e:
                return {'error': f'Replay execution failed: {str(e)}'}
                
        except Exception as e:
            return {'error': str(e)}
    
    def _replay_object_method(self, module_name, function_name, args, kwargs):
        """重放对象方法调用"""
        try:
            # 解析对象方法调用
            if '.' in function_name:
                class_name, method_name = function_name.rsplit('.', 1)
            else:
                return {'error': 'Invalid object method format'}
            
            # 查找类的实例
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
            
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, class_name):
                return {'error': f'Class {class_name} not found in module {module_name}'}
            
            class_obj = getattr(module_obj, class_name)
            if not inspect.isclass(class_obj):
                return {'error': f'{class_name} is not a class'}
            
            # 查找类的实例
            instances = []
            for obj in gc.get_objects():
                if isinstance(obj, class_obj):
                    instances.append(obj)
            
            if not instances:
                return {'error': f'No instances of {class_name} found'}
            
            result = {
                'success': True,
                'message': 'Object method replay information prepared',
                'replay_info': {
                    'module': module_name,
                    'class': class_name,
                    'method': method_name,
                    'args_repr': args,
                    'kwargs_repr': kwargs,
                    'available_instances': len(instances),
                    'note': 'Arguments are string representations. Manual reconstruction may be needed.'
                }
            }
            
            # 添加到调用历史
            self.add_to_call_history('replay', module_name, function_name, [], {}, result)
            
            return result
            
        except Exception as e:
            return {'error': str(e)}
    
    def clear_history(self):
        """清空调用历史"""
        try:
            count = len(self.call_history)
            self.call_history = []
            self.history_counter = 0
            return {'success': True, 'message': f'Cleared {count} history records'}
        except Exception as e:
            return {'error': str(e)}
    
    def get_history_stats(self):
        """获取历史统计信息"""
        try:
            total_count = len(self.call_history)
            
            # 统计调用类型
            type_stats = {}
            module_stats = {}
            
            for record in self.call_history:
                call_type = record.get('type', 'unknown')
                module_name = record.get('module', 'unknown')
                
                type_stats[call_type] = type_stats.get(call_type, 0) + 1
                module_stats[module_name] = module_stats.get(module_name, 0) + 1
            
            return {
                'total_count': total_count,
                'type_distribution': type_stats,
                'module_distribution': module_stats,
                'latest_id': self.history_counter
            }
        except Exception as e:
            return {'error': str(e)}