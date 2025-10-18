def normalize_object_id(raw_id):
    """将前端传来的对象ID统一转换为int，用于内部查找。
    支持格式:
      - 纯数字字符串: "1234567890"
      - 0x/0X前缀十六进制: "0x7ffdeadbeef"
      - 含有十六进制但无前缀: "7ffdeadbeef" (当长度>=9并且包含a-f时尝试按hex解析)
      - 已经是int: 直接返回
    返回: (ok: bool, value_or_error)
    ok=True时 value_or_error为int
    ok=False时 value_or_error为错误消息
    """
    try:
        if raw_id is None:
            return False, 'object_id is None'
        # 已是整数
        if isinstance(raw_id, int):
            return True, raw_id
        # bytes -> decode
        if isinstance(raw_id, bytes):
            raw_id = raw_id.decode('utf-8', 'ignore')
        # 其他转字符串
        s = str(raw_id).strip()
        if not s:
            return False, 'empty object_id'
        # 0x十六进制
        if s.lower().startswith('0x'):
            try:
                return True, int(s, 16)
            except ValueError:
                return False, f'invalid hex object_id: {s}'
        # 纯数字
        if s.isdigit():
            try:
                return True, int(s)
            except ValueError:
                return False, f'invalid decimal object_id: {s}'
        # 含有十六进制字符尝试
        hex_chars = set('0123456789abcdefABCDEF')
        if all(c in hex_chars for c in s) and any(c in 'abcdefABCDEF' for c in s):
            try:
                return True, int(s, 16)
            except ValueError:
                return False, f'invalid implicit hex object_id: {s}'
        return False, f'unsupported object_id format: {s}'
    except Exception as e:
        return False, f'normalize error: {e}'


def format_object_id(obj):
    """返回标准化的对象ID表示: 十进制字符串与十六进制字符串"""
    try:
        oid = id(obj)
        return str(oid), hex(oid)
    except Exception:
        return None, None
