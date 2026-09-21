# 粗筛：找出前端里「被引用但没声明」和「跨函数误用同名局部量」的标识符。
# 扫的是 web/ 下那几个 <script>（见下面的 FILES），不是只有一个 app.js。
# 是启发式，不是正经 parser；输出的是候选，需要人眼看一遍。
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
#
# 2026-09-21 又修一次，加的是**作用域**：老版把四个 js 的 const/let/var/function
# 全收进一个扁平集合，不区分函数。于是
#   function pTasksHTML(){ const submitted = d.submitted; ... }
#   function bindTaskPage(){ if (submitted.length) ... }   // 引用的是别人的局部量
# 这种「名字在别处声明过、但此处看不见」的错，一律被判成「已声明」放过去。
# 家长端那颗「确认 / 退回」就是这么坏的：界面在、按钮在，点了 submitted is not defined。
# 现在分两步判：
#   a) 哪儿都没声明过 → 未声明候选（老口径）；
#   b) 声明过，但所有声明都在**不包含此处**的函数里 → 跨作用域引用候选（新口径）。
# b 这类必须报出来，它就是上面那种坏。
#
# 作用域是近似：只认 `function ...(...) {` 和 `(...) => {` 两种函数头，
# 类方法 / 对象字面量里的简写方法不认，块级作用域（if / for 的 {}）也不算。
# 认不出的地方一律按**更外层**算 —— 宁可漏报，也不误报：
# 误报会让这条自查链变噪声，噪声一多就没人看了，工具等于没有。
import re, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), 'web')

# v31 起前端不是一个文件了：app.js（家长端 + 公共）、child.js（孩子端那套「糖果冒险」）、
# candy-icons.js（孩子端的图标雪碧图）。v35 家长端换皮又多了 parent-icons.js
# （家长端的图标雪碧图）。这几个 <script> 在同一个页面里，全局是共享的，
# 所以**全局**声明必须合起来收集 —— 分开扫会把 S / api / CHILD / PARENT_ICONS
# 这类跨文件的名字全报成「未声明」。
FILES = ['candy-icons.js', 'parent-icons.js', 'app.js', 'child.js']

# 出现在这些字符后面的 / 是除号，不是正则开头
_DIV_AFTER = re.compile(r'[A-Za-z0-9_$\)\]]')
# 出现在这些词后面的 / 仍然是正则开头（return /re/.test(x)）
_REGEX_KW = {'return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete',
             'void', 'case', 'do', 'else', 'yield', 'await'}

_IDENT_CH = re.compile(r'[A-Za-z0-9_$]')
_IDENT = r'[A-Za-z_$][\w$]*'


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


# ---------------------------------------------------------------------------
# 作用域：给每个函数体框一个区间，位置就能问「你在哪个函数里」
# ---------------------------------------------------------------------------

def _brace_pairs(code):
    """开括号下标 -> 对应闭括号下标。涂过噪声之后，字符串和正则里的花括号
    已经没了，模板里的 ${ } 是配对的，所以这份配对是可信的。"""
    stack, pairs = [], {}
    for i, c in enumerate(code):
        if c == '{':
            stack.append(i)
        elif c == '}' and stack:
            pairs[stack.pop()] = i
    return pairs


def _body_open_after(code, i):
    """i 是 `function` 之后，返回函数体那个 { 的下标；括号深度归零后遇到的第一个。"""
    depth, n = 0, len(code)
    while i < n:
        c = code[i]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        elif c == '{' and depth <= 0:
            return i
        i += 1
    return -1


def _params_before(code, j):
    """j 是函数体 { 的下标，往回找紧挨着的 (...) 里的形参文本。"""
    k = j - 1
    while k >= 0 and code[k].isspace():
        k -= 1
    if k < 0 or code[k] != ')':
        return ''
    depth, end = 0, k
    while k >= 0:
        if code[k] == ')':
            depth += 1
        elif code[k] == '(':
            depth -= 1
            if depth == 0:
                return code[k + 1:end]
        k -= 1
    return ''


def _param_names(params):
    """形参文本 -> 名字列表。解构的取里面所有像名字的词，宁可多收。"""
    out = []
    for p in (params or '').split(','):
        p = p.strip().split('=')[0].strip()
        if p[:1] in ('{', '['):
            out += re.findall(_IDENT, p)
        elif re.fullmatch(_IDENT, p or ''):
            out.append(p)
    return out


def collect_scopes(code):
    """认出每个函数体：{start, end, params}。end 是闭括号下标，闭区间。

    返回 (scopes, loose)。loose 是**表达式体箭头函数**的形参 ——
    `S.members.find(x => x.id === id)` 里的 x。那种箭头没有块，框不出区间，
    所以它的形参只能挂到外层作用域上（宁可漏报）。
    不这么处理会满屏误报：`x`、`b`、`i` 这类单字母回调参数全是这个形状。
    """
    pairs = _brace_pairs(code)
    scopes, loose = [], []

    def add(open_at, params):
        if open_at in pairs:
            scopes.append({'start': open_at, 'end': pairs[open_at], 'params': params})

    for m in re.finditer(r'\bfunction\b', code):
        o = _body_open_after(code, m.end())
        if o >= 0:
            add(o, _params_before(code, o))
    for m in re.finditer(r'=>(?!=)', code):
        j = m.end()
        while j < len(code) and code[j].isspace():
            j += 1
        # 形参一律从 `=>` **前面**取：`(a, x) => a + x` 这种带括号的，
        # 从后面看只能看见一个 `>`，什么都取不到。
        back = re.search(r'(' + _IDENT + r')\s*$', code[:m.start()])
        text = back.group(1) if back else _params_before(code, m.start())
        if j < len(code) and code[j] == '{':
            add(j, text)
        else:
            for name in _param_names(text):
                loose.append((name, m.start()))
    return scopes, loose


def _innermost(scopes, pos):
    """pos 落在哪个函数的体里；不在任何函数里就返回 None（= 文件顶层，全局）。"""
    best, span = None, None
    for i, s in enumerate(scopes):
        if s['start'] <= pos <= s['end']:
            w = s['end'] - s['start']
            if span is None or w < span:
                best, span = i, w
    return best


def _chain(scopes, pos):
    """pos 一路往外经过的所有函数（闭包链）。"""
    return {i for i, s in enumerate(scopes) if s['start'] <= pos <= s['end']}


# ---------------------------------------------------------------------------
# 收集声明与引用
# ---------------------------------------------------------------------------

def _decl_rules(code):
    """产出 (名字, 位置)。规则与老版一致，只是多了位置。形参不在这里收，
    它们跟着 collect_scopes 走 —— 挂在外层会把作用域放宽，容易漏报。"""
    out = []
    for m in re.finditer(r'\b(?:function|const|let|var|class)\s+(' + _IDENT + r')', code):
        out.append((m.group(1), m.start(1)))
    # 一条 const/let 里逗号接了好几个：
    #   const go = $('#go', box), done = $('#pdone', box);
    # 只认关键字后面第一个名字的话，done 会被当成没声明，白报一次。
    for m in re.finditer(r'\b(?:const|let|var)\s+([^;\n]*)', code):
        for nm in re.findall(r'(?:^|,)\s*(' + _IDENT + r')\s*(?==|,|$)', m.group(1)):
            out.append((nm, m.start()))
    for m in re.finditer(r'catch\s*\(\s*(' + _IDENT + r')', code):
        out.append((m.group(1), m.start(1)))
    # 解构赋值里的名字：const { a, b } = ... / const [x, y] = ...
    for m in re.finditer(r'\b(?:const|let|var)\s*([\[{][^\]}]*[\]}])\s*=', code):
        for nm in re.findall(_IDENT, m.group(1)):
            out.append((nm, m.start()))
    return out


# JS/DOM 里本来就有的全局
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


def analyze(raw):
    """raw: {文件名: 源码}。返回 (未声明, 跨作用域)。

    未声明：哪儿都没声明过的名字 -> [(位置, ...)]
    跨作用域：声明过，但所有声明都在不包含此处的函数里 -> {名字: {'uses':…, 'decls':…}}
    """
    files = []
    for fn, txt in raw.items():
        code = strip_noise(txt)
        scopes, loose = collect_scopes(code)
        files.append((fn, code, scopes, loose))

    decls = {}          # 名字 -> {作用域id}；None 表示全局（文件顶层），全局可见
    for fn, code, scopes, loose in files:
        for name, pos in _decl_rules(code):
            idx = _innermost(scopes, pos)
            decls.setdefault(name, set()).add((fn, idx) if idx is not None else None)
        for si, sc in enumerate(scopes):
            for name in _param_names(sc['params']):
                decls.setdefault(name, set()).add((fn, si))
        for name, pos in loose:
            idx = _innermost(scopes, pos)
            decls.setdefault(name, set()).add((fn, idx) if idx is not None else None)

    refs = []           # (名字, '文件:行', 闭包链)

    def note(name, fn, code, scopes, pos):
        line = code[:pos].count('\n') + 1
        chain = {(fn, i) for i in _chain(scopes, pos)}
        refs.append((name, '%s:%d' % (fn, line), chain))

    for fn, code, scopes, _loose in files:
        # 被调用 / 被取属性的裸标识符
        for m in re.finditer(r'(?<![\w.$])(' + _IDENT + r')\s*(?:\(|\.)', code):
            note(m.group(1), fn, code, scopes, m.start())
        # `!x.length` 这类裸读（白屏事故的形态）
        for m in re.finditer(r'(?<![\w.$])(' + _IDENT + r')\.\s*length', code):
            note(m.group(1), fn, code, scopes, m.start())

    undeclared, cross = {}, {}
    for name, where, chain in refs:
        if name in KNOWN:
            continue
        if name not in decls:
            undeclared.setdefault(name, []).append(where)
            continue
        if None in decls[name] or (chain & decls[name]):
            continue
        cross.setdefault(name, {'uses': [], 'decls': []})
        cross[name]['uses'].append(where)

    for name, info in cross.items():
        seen = [loc for (f, i) in decls[name]
                for loc in [_where_of(files, f, i)] if loc]
        info['decls'] = list(dict.fromkeys(seen))
        info['uses'] = list(dict.fromkeys(info['uses']))
    return undeclared, cross


def _where_of(files, fn, scope_idx):
    """把作用域 id 说成人话：哪个文件、哪一行。全局返回 None。"""
    if scope_idx is None:
        return None
    for f, code, scopes, _loose in files:
        if f == fn:
            return '%s:%d' % (fn, code[:scopes[scope_idx]['start']].count('\n') + 1)
    return None


# ---------------------------------------------------------------------------
# 自测：假名夹具必须真报出来，干净样本必须一个都不报
# ---------------------------------------------------------------------------

_CLEAN = '''
const shared = 1;
function outer() {
  const inner = 2;
  return inner + shared;
}
const useShared = () => shared + outer();
'''

_BUG = '''
function pTasksHTML(d) {
  const submitted = d.submitted || [];
  return submitted.length;
}
function bindTaskPage(d) {
  if (submitted.length) { return 1; }
  return 0;
}
'''


def selftest():
    """改这个工具的人先跑它。夹具就是当年的那个坏：两个函数各有一个 d，
    第二个函数引了第一个函数的局部量 submitted。"""
    bad = 0
    un, cr = analyze({'clean.js': _CLEAN})
    if un or cr:
        bad = 1
        print('[自测失败] 干净样本不该有候选：未声明=%s 跨作用域=%s' % (un, cr))
    un, cr = analyze({'bug.js': _BUG})
    if 'submitted' not in cr:
        bad = 1
        print('[自测失败] 假名夹具没被报出来：未声明=%s 跨作用域=%s' % (un, cr))
    elif un:
        bad = 1
        print('[自测失败] 假名夹具不该有「未声明」：%s' % un)
    if bad:
        print('自测没过。')
        return 1
    print('自测通过：干净样本 0 候选，假名夹具报出了 submitted。')
    return 0


def main():
    if '--selftest' in sys.argv:
        return selftest()
    raw = {}
    for fn in FILES:
        p = os.path.join(WEB, fn)
        if os.path.exists(p):
            raw[fn] = open(p, encoding='utf-8').read()
        else:
            print('跳过（文件不在）：%s' % fn)
    undeclared, cross = analyze(raw)

    if not undeclared and not cross:
        print('OK：没有发现未声明的标识符，也没有跨函数误用的同名局部量')
        return 0

    if cross:
        print('跨函数误用同名局部量（声明在别的函数里，此处根本看不见）：')
        for name in sorted(cross, key=lambda k: -len(cross[k]['uses'])):
            info = cross[name]
            print('  %-18s 用在 %s；声明在 %s'
                  % (name, ' '.join(info['uses'][:6]), ' '.join(info['decls'][:6])))
    if undeclared:
        print('候选未声明标识符（按出现次数）：')
        for name in sorted(undeclared, key=lambda k: -len(undeclared[k])):
            where = list(dict.fromkeys(undeclared[name]))
            print('  %-22s %2d 次  %s' % (name, len(where), ' '.join(where[:10])))
    return 1


if __name__ == '__main__':
    sys.exit(main())
