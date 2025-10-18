import sys
import inspect
import gc
from id_utils import normalize_object_id

class MInsp:
    def __init__(self):
        self.module_cache = {}
        self.last_refresh_time = None
        self.cache_ttl = 5  # 秒

    def _safe_repr(self, obj, limit=160):
        try:
            r = repr(obj)
        except Exception as e:
            return f'<unrepr {e}>'
        if len(r) > limit:
            return r[:limit-3] + '...'
        return r
    
    def _find_object_by_id(self, object_id):
        """统一的对象查找方法，支持字符串十进制/十六进制ID"""
        ok, val = normalize_object_id(object_id)
        if not ok:
            return None
        try:
            target = val
            for obj in gc.get_objects():
                if id(obj) == target:
                    return obj
            return None
        except Exception:
            return None
    
    def dump_globals(self):
        """转储全局变量信息"""
        try:
            global_info = {}
            
            # 获取所有模块的全局变量
            for module_name, module_obj in sys.modules.copy().items():
                if not hasattr(module_obj, '__dict__'):
                    continue
                    
                module_globals = {}
                for key, value in module_obj.__dict__.copy().items():
                    if key.startswith('__') and key.endswith('__'):
                        continue
                        
                    try:
                        # 获取对象信息
                        obj_info = {
                            'type': str(type(value)),
                            'repr': repr(value),  # 限制长度
                            'id': str(id(value)),
                            'id_hex': hex(id(value))
                        }
                        
                        # 如果是类，添加方法信息
                        if inspect.isclass(value):
                            methods = [name for name, method in inspect.getmembers(value, inspect.isfunction)]
                            obj_info['methods'] = methods[:10]  # 限制数量
                            
                        # 如果是函数，添加签名信息
                        elif inspect.isfunction(value):
                            try:
                                obj_info['signature'] = str(inspect.signature(value))
                            except:
                                pass
                                
                        module_globals[key] = obj_info
                    except Exception as e:
                        module_globals[key] = {'error': str(e)}
                        
                if module_globals:
                    global_info[module_name] = module_globals
                    
            return global_info
        except Exception as e:
            return {'error': str(e)}
    
    def get_variable_value(self, module_name, variable_name):
        """获取模块变量的值"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, '__dict__'):
                return {'error': f'Module {module_name} has no __dict__'}
                
            if not hasattr(module_obj, variable_name):
                return {'error': f'Variable {variable_name} not found in module {module_name}'}
                
            value = getattr(module_obj, variable_name)
            
            return {
                'success': True,
                'variable_name': variable_name,
                'value': {
                    'type': type(value).__name__,
                    'repr': repr(value),
                    'id': str(id(value)),
                    'id_hex': hex(id(value)),
                    'str_value': str(value) if len(str(value)) <= 1000 else str(value)[:1000] + '...',
                    'is_callable': callable(value),
                    'is_class': inspect.isclass(value),
                    'is_function': inspect.isfunction(value),
                    'is_method': inspect.ismethod(value)
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def set_variable_value(self, module_name, variable_name, new_value, value_type='auto'):
        """设置模块变量的值"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, '__dict__'):
                return {'error': f'Module {module_name} has no __dict__'}
                
            # 类型转换
            try:
                if value_type == 'auto':
                    # 尝试自动推断类型
                    if isinstance(new_value, str):
                        # 尝试eval解析
                        try:
                            parsed_value = eval(new_value)
                            converted_value = parsed_value
                        except:
                            # 如果eval失败，保持字符串
                            converted_value = new_value
                    else:
                        converted_value = new_value
                elif value_type == 'str':
                    converted_value = str(new_value)
                elif value_type == 'int':
                    converted_value = int(new_value)
                elif value_type == 'float':
                    converted_value = float(new_value)
                elif value_type == 'bool':
                    if isinstance(new_value, str):
                        converted_value = new_value.lower() in ('true', '1', 'yes', 'on')
                    else:
                        converted_value = bool(new_value)
                elif value_type == 'list':
                    if isinstance(new_value, str):
                        converted_value = eval(new_value)
                    else:
                        converted_value = list(new_value)
                elif value_type == 'dict':
                    if isinstance(new_value, str):
                        converted_value = eval(new_value)
                    else:
                        converted_value = dict(new_value)
                elif value_type == 'eval':
                    converted_value = eval(new_value)
                else:
                    converted_value = new_value
                    
            except Exception as e:
                return {'error': f'Type conversion failed: {str(e)}'}
                
            # 设置变量值
            old_value = getattr(module_obj, variable_name, None)
            setattr(module_obj, variable_name, converted_value)
            
            return {
                'success': True,
                'variable_name': variable_name,
                'old_value': {
                    'type': type(old_value).__name__ if old_value is not None else 'None',
                    'repr': repr(old_value) if old_value is not None else 'None'
                },
                'new_value': {
                    'type': type(converted_value).__name__,
                    'repr': repr(converted_value),
                    'id': str(id(converted_value)),
                    'id_hex': hex(id(converted_value))
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_object_attribute_value(self, object_id, attribute_name):
        """获取对象属性的值"""
        try:
            # 使用统一的对象查找方法
            target_obj = self._find_object_by_id(object_id)
            if target_obj is None:
                return {'error': 'Object not found'}
                
            if not hasattr(target_obj, attribute_name):
                return {'error': f'Attribute {attribute_name} not found'}
                
            value = getattr(target_obj, attribute_name)
            
            return {
                'success': True,
                'object_id': str(object_id),
                'attribute_name': attribute_name,
                'value': {
                    'type': type(value).__name__,
                    'repr': repr(value),
                    'id': str(id(value)),
                    'id_hex': hex(id(value)),
                    'str_value': str(value) if len(str(value)) <= 1000 else str(value)[:1000] + '...',
                    'is_callable': callable(value),
                    'is_class': inspect.isclass(value),
                    'is_function': inspect.isfunction(value),
                    'is_method': inspect.ismethod(value)
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def set_object_attribute_value(self, object_id, attribute_name, new_value, value_type='auto'):
        """设置对象属性的值"""
        try:
            # 使用统一的对象查找方法
            target_obj = self._find_object_by_id(object_id)
            if target_obj is None:
                return {'error': 'Object not found'}
                
            # 类型转换（与set_variable_value相同的逻辑）
            try:
                if value_type == 'auto':
                    if isinstance(new_value, str):
                        try:
                            parsed_value = eval(new_value)
                            converted_value = parsed_value
                        except:
                            converted_value = new_value
                    else:
                        converted_value = new_value
                elif value_type == 'str':
                    converted_value = str(new_value)
                elif value_type == 'int':
                    converted_value = int(new_value)
                elif value_type == 'float':
                    converted_value = float(new_value)
                elif value_type == 'bool':
                    if isinstance(new_value, str):
                        converted_value = new_value.lower() in ('true', '1', 'yes', 'on')
                    else:
                        converted_value = bool(new_value)
                elif value_type == 'list':
                    if isinstance(new_value, str):
                        converted_value = eval(new_value)
                    else:
                        converted_value = list(new_value)
                elif value_type == 'dict':
                    if isinstance(new_value, str):
                        converted_value = eval(new_value)
                    else:
                        converted_value = dict(new_value)
                elif value_type == 'eval':
                    converted_value = eval(new_value)
                else:
                    converted_value = new_value
                    
            except Exception as e:
                return {'error': f'Type conversion failed: {str(e)}'}
                
            # 设置属性值
            old_value = getattr(target_obj, attribute_name, None)
            setattr(target_obj, attribute_name, converted_value)
            
            return {
                'success': True,
                'object_id': str(object_id),
                'attribute_name': attribute_name,
                'old_value': {
                    'type': type(old_value).__name__ if old_value is not None else 'None',
                    'repr': repr(old_value) if old_value is not None else 'None'
                },
                'new_value': {
                    'type': type(converted_value).__name__,
                    'repr': repr(converted_value),
                    'id': str(id(converted_value)),
                    'id_hex': hex(id(converted_value))
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_modules_list(self):
        """获取所有模块列表"""
        try:
            modules = []
            for module_name, module_obj in sys.modules.copy().items():
                if hasattr(module_obj, '__dict__'):
                    modules.append({
                        'name': module_name,
                        'file': getattr(module_obj, '__file__', 'built-in'),
                        'package': getattr(module_obj, '__package__', None)
                    })
            return {'modules': modules}
        except Exception as e:
            return {'error': str(e)}
    
    def get_module_members(self, module_name):
        """获取指定模块的成员"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, '__dict__'):
                return {'error': f'Module {module_name} has no __dict__'}
                
            members = []
            for key, value in module_obj.__dict__.copy().items():
                if key.startswith('__') and key.endswith('__'):
                    continue
                    
                try:
                    member_info = {
                        'name': key,
                        'type': type(value).__name__,
                        'repr': repr(value),
                        'id': str(id(value)),
                        'id_hex': hex(id(value))
                    }
                    
                    if inspect.isclass(value):
                        member_info['is_class'] = True
                        member_info['methods'] = [name for name, method in inspect.getmembers(value, inspect.ismethod)]
                        member_info['functions'] = [name for name, func in inspect.getmembers(value, inspect.isfunction)]
                    elif inspect.isfunction(value):
                        member_info['is_function'] = True
                        try:
                            member_info['signature'] = str(inspect.signature(value))
                        except:
                            pass
                    elif inspect.ismethod(value):
                        member_info['is_method'] = True
                        try:
                            member_info['signature'] = str(inspect.signature(value))
                        except:
                            pass
                    elif callable(value) and member_info['type'] == 'builtin_function_or_method':
                        member_info['is_builtin_function'] = True
                        try:
                            member_info['signature'] = str(inspect.signature(value))
                        except:
                            # 对于内置函数，尝试获取文档字符串作为签名信息
                            if hasattr(value, '__doc__') and value.__doc__:
                                doc_lines = value.__doc__.split('\n')
                                if doc_lines:
                                    member_info['signature'] = doc_lines[0]
                            else:
                                member_info['signature'] = 'builtin function'
                            
                    members.append(member_info)
                except Exception as e:
                    members.append({'name': key, 'error': str(e)})
                    
            return {'members': members}
        except Exception as e:
            return {'error': str(e)}
    
    def get_module_submodules(self, module_name):
        """获取指定模块的子模块"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, '__dict__'):
                return {'error': f'Module {module_name} has no __dict__'}
                
            submodules = []
            
            # 查找所有以当前模块名开头的子模块
            for mod_name, mod_obj in sys.modules.copy().items():
                # 检查是否是子模块
                if (mod_name.startswith(module_name + '.') and 
                    mod_name != module_name and 
                    hasattr(mod_obj, '__dict__')):
                    
                    # 只获取直接子模块，不包括孙模块
                    relative_name = mod_name[len(module_name) + 1:]
                    if '.' not in relative_name:
                        try:
                            submodule_info = {
                                'name': mod_name,
                                'short_name': relative_name,
                                'file': getattr(mod_obj, '__file__', 'built-in'),
                                'package': getattr(mod_obj, '__package__', None),
                                'repr': repr(mod_obj),
                                'type': type(mod_obj).__name__
                            }
                            submodules.append(submodule_info)
                        except Exception as e:
                            submodules.append({
                                'name': mod_name,
                                'short_name': relative_name,
                                'error': str(e)
                            })
            
            # 同时检查模块内部是否有模块类型的成员
            for key, value in module_obj.__dict__.copy().items():
                if (not key.startswith('__') and 
                    inspect.ismodule(value) and 
                    hasattr(value, '__name__')):
                    
                    try:
                        # 检查是否已经在子模块列表中
                        if not any(sub['name'] == value.__name__ for sub in submodules):
                            submodule_info = {
                                'name': value.__name__,
                                'short_name': key,
                                'file': getattr(value, '__file__', 'built-in'),
                                'package': getattr(value, '__package__', None),
                                'repr': repr(value),
                                'type': 'module',
                                'is_member': True  # 标记这是作为成员存在的模块
                            }
                            submodules.append(submodule_info)
                    except Exception as e:
                        submodules.append({
                            'name': getattr(value, '__name__', key),
                            'short_name': key,
                            'error': str(e),
                            'is_member': True
                        })
                        
            return {'submodules': submodules}
        except Exception as e:
            return {'error': str(e)}
    
    def get_class_definition(self, module_name, class_name):
        """获取类定义信息"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, class_name):
                return {'error': f'Class {class_name} not found in module {module_name}'}
                
            class_obj = getattr(module_obj, class_name)
            if not inspect.isclass(class_obj):
                return {'error': f'{class_name} is not a class'}
                
            # 获取类的详细信息
            class_info = {
                'name': class_name,
                'module': module_name,
                'bases': [base.__name__ for base in class_obj.__bases__],
                'mro': [cls.__name__ for cls in class_obj.__mro__],
                'doc': class_obj.__doc__,
                'methods': [],
                'properties': [],
                'attributes': [],
                'variables': []  # 仅类级变量（排除函数/方法/property/dunder），并标注来源
            }
            
            # 获取方法和属性
            # 先记录所有成员（包含继承）
            for name, member in inspect.getmembers(class_obj):
                # 跳过私有方法，但保留构造函数和特殊方法
                if name.startswith('_') and name not in ['__init__', '__new__', '__call__', '__str__', '__repr__', '__len__', '__getitem__', '__setitem__', '__delitem__', '__iter__', '__next__', '__enter__', '__exit__', '__add__', '__sub__', '__mul__', '__div__', '__truediv__', '__floordiv__', '__mod__', '__pow__', '__and__', '__or__', '__xor__', '__lshift__', '__rshift__', '__lt__', '__le__', '__eq__', '__ne__', '__gt__', '__ge__', '__hash__', '__bool__', '__bytes__', '__format__', '__getattr__', '__setattr__', '__delattr__', '__dir__', '__get__', '__set__', '__delete__', '__instancecheck__', '__subclasscheck__']:
                    continue
                    
                try:
                    if inspect.ismethod(member) or inspect.isfunction(member):
                        method_info = {
                            'name': name,
                            'type': 'method' if inspect.ismethod(member) else 'function'
                        }
                        
                        # 标记构造函数和特殊方法
                        if name in ['__init__', '__new__']:
                            method_info['is_constructor'] = True
                        if name.startswith('__') and name.endswith('__'):
                            method_info['is_special'] = True
                            
                        try:
                            method_info['signature'] = str(inspect.signature(member))
                        except:
                            pass
                        class_info['methods'].append(method_info)
                    elif isinstance(member, property):
                        class_info['properties'].append({
                            'name': name,
                            'type': 'property',
                            'doc': member.__doc__
                        })
                    else:
                        # 先作为通用 attribute 收集（稍后过滤出 class variables）
                        class_info['attributes'].append({
                            'name': name,
                            'type': type(member).__name__,
                            'repr': self._safe_repr(member)
                        })
                except Exception as e:
                    class_info['attributes'].append({'name': name, 'error': str(e)})

            # ========== 类级变量提取 ==========
            # 判定规则：
            # 1. 名称不以 '__' 开头（排除 dunder）
            # 2. 不是方法/函数/property（已被前面分类掉）
            # 3. 来自某个定义类的 __dict__（遍历 MRO）
            # 4. 不是描述符（排除有 __get__ 且同时有 __set__/__delete__ 的数据描述符；保留普通对象、常量、简单值）
            seen = set()
            for mro_cls in class_obj.__mro__:
                if mro_cls is object:
                    continue
                for k, v in mro_cls.__dict__.items():
                    if k in seen:
                        continue
                    seen.add(k)
                    if k.startswith('__'):
                        continue
                    # 跳过函数/方法/staticmethod/classmethod/property
                    if inspect.isfunction(v) or inspect.ismethod(v):
                        continue
                    if isinstance(v, (staticmethod, classmethod, property)):
                        continue
                    # 数据描述符判定（更偏向行为属性，不当作简单变量）
                    if hasattr(v, '__get__') and (hasattr(v, '__set__') or hasattr(v, '__delete__')):
                        continue
                    var_info = {
                        'name': k,
                        'defined_in': mro_cls.__name__,
                        'own': mro_cls is class_obj,
                        'type': type(v).__name__,
                        'repr': self._safe_repr(v)
                    }
                    # 尝试提供 size hint
                    try:
                        if isinstance(v, (list, tuple, set, dict, str, bytes)):
                            var_info['size'] = len(v)
                    except Exception:
                        pass
                    class_info['variables'].append(var_info)
                    
            return class_info
        except Exception as e:
            return {'error': str(e)}
    
    def get_class_instances(self, module_name, class_name, page=1, page_size=20):
        """使用gc获取类的所有实例，支持分页"""
        try:
            if module_name not in sys.modules:
                return {'error': f'Module {module_name} not found'}
                
            module_obj = sys.modules[module_name]
            if not hasattr(module_obj, class_name):
                return {'error': f'Class {class_name} not found in module {module_name}'}
                
            class_obj = getattr(module_obj, class_name)
            if not inspect.isclass(class_obj):
                return {'error': f'{class_name} is not a class'}
                
            # 使用gc获取所有实例
            all_instances = []
            for obj in gc.get_objects():
                if isinstance(obj, class_obj):
                    try:
                        instance_info = {
                            'id': str(id(obj)),
                            'id_hex': hex(id(obj)),
                            'repr': repr(obj),
                            'type': type(obj).__name__,
                            'attributes': {}
                        }
                        
                        # 获取实例属性（限制数量避免过大）
                        if hasattr(obj, '__dict__'):
                            for key, value in list(obj.__dict__.items())[:10]:  # 限制10个属性
                                try:
                                    instance_info['attributes'][key] = {
                                        'type': type(value).__name__,
                                        'repr': repr(value)
                                    }
                                except:
                                    instance_info['attributes'][key] = {'error': 'Cannot represent'}
                                    
                        all_instances.append(instance_info)
                    except:
                        continue
            
            # 计算分页
            total_count = len(all_instances)
            total_pages = (total_count + page_size - 1) // page_size
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            
            # 获取当前页的实例
            page_instances = all_instances[start_index:end_index]
            
            return {
                'instances': page_instances,
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
    
    def get_object_details(self, object_id):
        """获取对象详细信息"""
        try:
            # 使用统一的对象查找方法
            target_obj = self._find_object_by_id(object_id)
            if target_obj is None:
                return {'error': 'Object not found'}
            
            # 安全地获取基本信息
            obj_info = {
                'id': str(id(target_obj)),
                'id_hex': hex(id(target_obj)),
                'attributes': {},
                'methods': []
            }
            
            # 安全地获取类型信息
            try:
                obj_info['type'] = type(target_obj).__name__
            except Exception as type_error:
                obj_info['type'] = f'<type error: {str(type_error)}>'
            
            # 安全地获取repr信息
            try:
                obj_info['repr'] = repr(target_obj)
            except Exception as repr_error:
                obj_info['repr'] = f'<repr error: {str(repr_error)}>'
            
            # 添加对象的模块信息（如果可用）
            try:
                if hasattr(target_obj, '__module__'):
                    obj_info['module'] = target_obj.__module__
            except:
                pass
            
            # 添加对象的类信息
            try:
                obj_info['class'] = target_obj.__class__.__name__
                if hasattr(target_obj.__class__, '__module__'):
                    obj_info['class_module'] = target_obj.__class__.__module__
            except:
                pass
            
            # 获取属性 - 使用更安全的方式
            try:
                # 首先尝试使用__dict__
                if hasattr(target_obj, '__dict__') and target_obj.__dict__ is not None:
                    for key, value in target_obj.__dict__.items():
                        try:
                            obj_info['attributes'][key] = {
                                'type': type(value).__name__,
                                'repr': repr(value),
                                'id': str(id(value)),
                                'id_hex': hex(id(value))
                            }
                        except Exception as attr_error:
                            obj_info['attributes'][key] = {'error': f'Cannot represent: {str(attr_error)}'}
                else:
                    # 如果没有__dict__，尝试使用dir()和getattr()
                    for attr_name in dir(target_obj):
                        if not attr_name.startswith('_'):  # 跳过私有属性
                            try:
                                value = getattr(target_obj, attr_name)
                                # 跳过方法和函数
                                if not (inspect.ismethod(value) or inspect.isfunction(value) or callable(value)):
                                    obj_info['attributes'][attr_name] = {
                                        'type': type(value).__name__,
                                        'repr': repr(value),
                                        'id': str(id(value)),
                                        'id_hex': hex(id(value))
                                    }
                            except (AttributeError, TypeError, ValueError) as attr_error:
                                obj_info['attributes'][attr_name] = {'error': f'Cannot access: {str(attr_error)}'}
                            except Exception as general_error:
                                obj_info['attributes'][attr_name] = {'error': f'General error: {str(general_error)}'}
            except Exception as dict_error:
                # 如果所有属性获取方法都失败，记录错误但继续
                obj_info['attributes'] = {'_error': f'Failed to get attributes: {str(dict_error)}'}
                        
            # 获取方法 - 使用更安全的方式避免描述符错误
            try:
                # 先尝试使用dir()获取属性名，然后安全地获取每个属性
                for name in dir(target_obj):
                    # 跳过私有方法，但保留构造函数和常用特殊方法
                    if name.startswith('_') and name not in ['__init__', '__new__', '__call__', '__str__', '__repr__']:
                        continue
                    try:
                        member = getattr(target_obj, name)
                        if inspect.ismethod(member) or inspect.isfunction(member):
                            method_info = {
                                'name': name,
                                'type': 'method' if inspect.ismethod(member) else 'function',
                                'is_constructor': name in ['__init__', '__new__'],
                                'is_special': name.startswith('__') and name.endswith('__')
                            }
                            try:
                                method_info['signature'] = str(inspect.signature(member))
                            except:
                                pass
                            obj_info['methods'].append(method_info)
                    except (AttributeError, TypeError, ValueError) as attr_error:
                        # 跳过无法访问的属性
                        continue
            except Exception as method_error:
                # 如果dir()也失败，则回退到inspect.getmembers但增加更细粒度的错误处理
                try:
                    for name, member in inspect.getmembers(target_obj, lambda x: True):
                        if not name.startswith('_') and (inspect.ismethod(member) or inspect.isfunction(member)):
                            try:
                                method_info = {
                                    'name': name,
                                    'type': 'method' if inspect.ismethod(member) else 'function'
                                }
                                try:
                                    method_info['signature'] = str(inspect.signature(member))
                                except:
                                    pass
                                obj_info['methods'].append(method_info)
                            except:
                                continue
                except:
                    # 如果所有方法都失败，至少返回基本信息
                    obj_info['methods'] = []
                        
            return obj_info
        except Exception as e:
            # 提供更详细的错误信息用于调试
            import traceback
            error_info = {
                'error': str(e),
                'error_type': type(e).__name__,
                'traceback': traceback.format_exc(),
                'object_id': object_id
            }
            # 尝试获取一些基本信息，即使在错误情况下
            try:
                found_obj = self._find_object_by_id(object_id)
                if found_obj is not None:
                    error_info['found_object'] = True
                    try:
                        error_info['object_type'] = type(found_obj).__name__
                    except:
                        error_info['object_type'] = '<unknown>'
                else:
                    error_info['found_object'] = False
            except:
                error_info['gc_search_failed'] = True
            
            return error_info
    
    def call_object_method(self, object_id, method_name, args=None, kwargs=None):
        """调用对象方法，支持内置函数和方法"""
        try:
            # 使用统一的对象查找方法
            target_obj = self._find_object_by_id(object_id)
            if target_obj is None:
                return {'error': 'Object not found'}
                
            if not hasattr(target_obj, method_name):
                return {'error': f'Method {method_name} not found'}
                
            method = getattr(target_obj, method_name)
            
            # 检查是否可调用，支持内置函数和方法
            if not callable(method):
                return {'error': f'{method_name} is not callable'}
                
            # 调用方法
            if args is None:
                args = []
            if kwargs is None:
                kwargs = {}
                
            # 特殊处理内置函数和方法
            method_type = type(method).__name__
            try:
                if method_type in ['builtin_function_or_method', 'method-wrapper', 'builtin_method_or_function']:
                    # 对于内置函数，尝试直接调用
                    result = method(*args, **kwargs)
                else:
                    result = method(*args, **kwargs)
                    
                return {
                    'success': True,
                    'result': {
                        'type': type(result).__name__,
                        'repr': repr(result),
                        'id': str(id(result)),
                        'id_hex': hex(id(result))
                    }
                }
            except Exception as e:
                import traceback
                return {'success': False, 'error': traceback.format_exc()}
                
        except Exception as e:
            import traceback
            return {'error': traceback.format_exc()}