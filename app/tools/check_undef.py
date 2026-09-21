# 粗筛：找出前端里「被引用但没声明」的标识符。
# 扫的是 web/ 下那几个 <script>（见下面的 FILES），不是只有一个 app.js。
# 不是精确的 scope 分析，是启发式；输出的是候选，需要人眼看一遍。
# 存在的意义：node --check 只查语法，查不出 `done is not defined` 这类运行时错误，
# 而这类错误会让整块界面空白（跟白屏事故同一类）。
#
# 2026-09-19 修过一次：老版本的剥噪声只认引号，遇到 app.js 第 8 行的
#   .replace(/[&<>"']/g, ...)
# 就把正则里那个引号当成字符串开头，从这里往后的四千行全被吃进一个
# 「字符串」里。结果是它只扫到 16 个声明，候选清单照样打出一堆名字，
# 看着像在工作，其实等于没查 —— 这个工具存在的唯一理由就这么被抹掉了。
# 现在：注释 / 字符串 / 模板 / 正则字面量全部换成**等长空格**（换行保留），
# 行号不再漂移；模板里的 ${...} 还算代码，正则按前一个字符判断是除号还是正则。
import re, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), 'web')

# v31 起前端不是一个文件了：app.js（家长端 + 公共）、child.js（孩子端那套「糖果冒险」）、
# candy-icons.js（孩子端的图标雪碧图）。v35 家长端换皮又多了 parent-icons.js
# （家长端的图标雪碧图）。这几个 <script> 在同一个页面里，全局是共享的，
# 所以声明必须合起来收集 —— 分开扫会把 S / api / CHILD / PARENT_ICONS
# 这类跨文件的名字全报成「未声明」。
FILES = ['candy-icons.js', 'parent-icons.js', 'app.js', 'child.js']

RAW = {}
for _fn in FILES:
    _p = os.path.join(WEB, _fn)
    if os.path.exists(_p):
        RAW[_fn] = open(_p, encoding='utf-8').read()
    else:
        print('跳过（文件不在）：%s' % _fn)

# 出现在这些字符后面的 / 是除号，不是正则开头
_DIV_AFTER = re.compile(r'[A-Za-z0-9_$\)\]]')
# 出现在这些词后面的 / 仍然是正则开头（return /re/.test(x)）
_REGEX_KW = {'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete',
             'void', 'case', 'do', 'else', 'yield', 'await'}

_IDENT_CH = re.compile(r'[A-Za-z0-9_$]')


def _mask(chunk):
    """等长涂掉，换行留着 —— 行号必须和源文件对得上。"""
    return ''.join('\n' if ch == '\n' else ' ' for ch in chunk)


def _end_of_string(s, i):
    """s[i] 是引号，返回字符串结束后的下标。"""
    q, n, j = s[i], len(s), i + 1
    while j < n:
        if s[j] == '\\':
            j += 2
            continue
        if s[j] == q:
            return j + 1
        j += 1
    return n


def _end_of_regex(s, i):
    """s[i] 是 /，返回正则字面量结束后的下标；看着不像正则就返回 i。"""
    n, j, in_class = len(s), i + 1, False
    while j < n:
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == '\n':
            return i                      # 正则不跨行，说明这是除号
        if in_class:
            if c == ']':
                in_class = False
        elif c == '[':
            in_class = True
        elif c == '/':
            j += 1
            while j < n and s[j].isalpha():   # 标志位 gimsuy
                j += 1
            return j
        j += 1
    return i


def _template(s, i):
    """处理反引号模板：字面部分涂掉，${...} 里的代码原样留下。"""
    n, out = len(s), [' ']
    i += 1
    while i < n:
        c = s[i]
        if c == '\\':
            out.append('  ' if i + 1 < n else ' ')
            i += 2
            continue
        if c == '`':
            out.append(' ')
            return ''.join(out), i + 1
        if c == '$' and i + 1 < n and s[i + 1] == '{':
            out.append('${')
            i += 2
            depth = 1
            while i < n:
                ch = s[i]
                if ch == '`':
                    sub, i = _template(s, i)
                    out.append(sub)
                    continue
                if ch in '"\'`':
                    end = _end_of_string(s, i)
                    out.append(_mask(s[i:end]))
                    i = end
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        out.append('}')
                        i += 1
                        break
                out.append('\n' if ch == '\n' else ch)
                i += 1
            continue
        out.append('\n' if c == '\n' else ' ')
        i += 1
    return ''.join(out), i


def strip_noise(s):
    out, i, n = [], 0, len(s)
    prev, word, cur = '', '', ''
    while i < n:
        c = s[i]
        if c == '/' and i + 1 < n and s[i + 1] == '/':
            j = s.find('\n', i)
            j = n if j < 0 else j
            out.append(_mask(s[i:j]))
            i = j
            continue
        if c == '/' and i + 1 < n and s[i + 1] == '*':
            j = s.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append(_mask(s[i:j]))
            i = j
            continue
        if c == '/' and not (_DIV_AFTER.match(prev) and word not in _REGEX_KW):
            j = _end_of_regex(s, i)
            if j > i:
                out.append(_mask(s[i:j]))
                i = j
                prev, word, cur = 'x', '', ''
                continue
        if c == '`':
            chunk, i = _template(s, i)
            out.append(chunk)
            prev, word, cur = 'x', '', ''
            continue
        if c == '"' or c == "'":
            j = _end_of_string(s, i)
            out.append(_mask(s[i:j]))
            i = j
            prev, word, cur = 'x', '', ''
            continue
        out.append(c)
        if _IDENT_CH.match(c):
            cur += c
        elif not c.isspace():
            if cur:
                word = cur
            cur = ''
        if not c.isspace():
            prev = c
        i += 1
    return ''.join(out)


CODES = [(fn, strip_noise(txt)) for fn, txt in RAW.items()]
# 收集声明这一步不看行号，合成一份扫就够了。
code = '\n'.join(c for _, c in CODES)

# 2) 收集声明过的名字
declared = set()
for m in re.finditer(r'\b(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)', code):
    declared.add(m.group(1))
# 一条 const/let 里逗号接了好几个：
#   const go = $('#go', box), done = $('#pdone', box);
# 只认关键字后面第一个名字的话，done 会被当成没声明，白报一次。
for m in re.finditer(r'\b(?:const|let|var)\s+([^;\n]*)', code):
    for name in re.findall(r'(?:^|,)\s*([A-Za-z_$][\w$]*)\s*(?==|,|$)', m.group(1)):
        declared.add(name)
# 函数参数、catch 参数、箭头函数参数（够用的近似）
for m in re.finditer(r'function\s*[A-Za-z_$\w]*\s*\(([^)]*)\)', code):
    for p in m.group(1).split(','):
        p = p.strip().split('=')[0].strip()
        if re.fullmatch(r'[A-Za-z_$][\w$]*', p or ''):
            declared.add(p)
for m in re.finditer(r'\(([^()]*)\)\s*=>', code):
    for p in m.group(1).split(','):
        p = p.strip().split('=')[0].strip()
        if re.fullmatch(r'[A-Za-z_$][\w$]*', p or ''):
            declared.add(p)
# 单个参数的箭头函数：b => ...
for m in re.finditer(r'(?<![\w.$])([A-Za-z_$][\w$]*)\s*=>', code):
    declared.add(m.group(1))
for m in re.finditer(r'\bcatch\s*\(\s*([A-Za-z_$][\w$]*)', code):
    declared.add(m.group(1))
# 解构赋值里的名字：const { a, b } = ... / const [x, y] = ...
for m in re.finditer(r'\b(?:const|let|var)\s*([\[{][^\]}]*[\]}])\s*=', code):
    for name in re.findall(r'[A-Za-z_$][\w$]*', m.group(1)):
        declared.add(name)
# 属性简写的对象字面量、类字段之类不处理 —— 有疑问的会以候选形式冒出来，人眼看。

# 3) JS/DOM 里本来就有的全局
KNOWN = {
    'window', 'document', 'console', 'Math', 'JSON', 'Object', 'Array', 'String', 'Number',
    'Boolean', 'Date', 'RegExp', 'Error', 'Promise', 'Map', 'Set', 'Symbol', 'Proxy', 'Reflect',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent', 'decodeURIComponent',
    'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'requestAnimationFrame',
    'fetch', 'alert', 'confirm', 'prompt', 'location', 'navigator', 'history', 'localStorage',
    'sessionStorage', 'Infinity', 'NaN', 'undefined', 'null', 'true', 'false', 'this',
    'if', 'for', 'while', 'switch', 'catch', 'return', 'typeof', 'new', 'delete', 'void',
    'in', 'of', 'do', 'else', 'try', 'finally', 'throw', 'case', 'break', 'continue',
    'function', 'class', 'const', 'let', 'var', 'await', 'async', 'yield', 'super', 'default',
    'get', 'set', 'static', 'extends', 'import', 'export', 'from', 'with', 'instanceof',
    'matchMedia', 'getComputedStyle', 'URLSearchParams', 'FormData', 'Blob', 'Intl',
    'addEventListener', 'removeEventListener', 'dispatchEvent', 'CustomEvent', 'Event',
    'Blob', 'FileReader', 'Image', 'Audio', 'TextEncoder', 'TextDecoder', 'AbortController',
    # URL 这类老牌全局
    'URL', 'URLSearchParams', 'TextEncoder',
    # 本项目的两个旁挂脚本（icons.js / avatars.js 先于 app.js 加载）
    'ICONS', 'AVATARS',
}

# 4) 找被调用 / 被取属性的裸标识符
cands = {}


def _add(name, where):
    if name in declared or name in KNOWN:
        return
    cands.setdefault(name, []).append(where)


for _fn, code in CODES:
    for m in re.finditer(r'(?<![\w.$])([A-Za-z_$][\w$]*)\s*(?:\(|\.)', code):
        _add(m.group(1), '%s:%d' % (_fn, code[:m.start()].count('\n') + 1))
    # 5) 也查 `!x.length` 这类裸读（白屏事故的形态）
    for m in re.finditer(r'(?<![\w.$])([A-Za-z_$][\w$]*)\.\s*length', code):
        _add(m.group(1), '%s:%d' % (_fn, code[:m.start()].count('\n') + 1))

if not cands:
    print('OK：没有发现未声明的标识符候选')
    sys.exit(0)

print('候选未声明标识符（按出现次数）：')
for name in sorted(cands, key=lambda k: -len(cands[k])):
    where = list(dict.fromkeys(cands[name]))       # 同一个位置只报一次
    print('  %-22s %2d 次  %s' % (name, len(cands[name]), ' '.join(where[:10])))
