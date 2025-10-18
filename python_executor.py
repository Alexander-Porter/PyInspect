import sys
import io
import traceback

class Executor:
    def __init__(self):
        self.session_globals = {'__name__': '__main__', '__builtins__': __builtins__}
    
    def execute_code(self, code):
        """执行Python代码并返回结果"""
        try:
            # 捕获输出
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            captured_output = io.StringIO()
            sys.stdout = captured_output
            sys.stderr = captured_output
            
            try:
                # 尝试作为表达式编译
                try:
                    compiled_code = compile(code, '<interactive>', 'eval')
                    result = eval(compiled_code, self.session_globals)
                    output = captured_output.getvalue()
                    if result is not None:
                        if output:
                            output += '\n' + repr(result)
                        else:
                            output = repr(result)
                    return {'success': True, 'output': output}
                except SyntaxError:
                    # 如果不是表达式，则作为语句执行
                    compiled_code = compile(code, '<interactive>', 'exec')
                    exec(compiled_code, self.session_globals)
                    output = captured_output.getvalue()
                    return {'success': True, 'output': output}
            except Exception as e:
                error_output = captured_output.getvalue()
                error_msg = f"{error_output}\n{traceback.format_exc()}"
                return {'success': False, 'error': error_msg}
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def reset_session(self):
        """重置Python会话"""
        self.session_globals = {'__name__': '__main__', '__builtins__': __builtins__}
        return {'success': True, 'message': 'Session reset'}
    
    def get_session_variables(self):
        """获取会话变量"""
        try:
            variables = {}
            for key, value in self.session_globals.items():
                if not key.startswith('__') or not key.endswith('__'):
                    try:
                        variables[key] = {
                            'type': type(value).__name__,
                            'repr': repr(value),
                            'id': id(value)
                        }
                    except:
                        variables[key] = {'error': 'Cannot represent'}
            return {'success': True, 'variables': variables}
        except Exception as e:
            return {'success': False, 'error': str(e)}