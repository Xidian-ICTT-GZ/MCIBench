"""C input-only invocation and JSON output, including pointer-size contracts."""
from local.harness.typespec import PlainSig, UnsupportedProblemError

SERIALIZER = r'''
static void mci_size(int n) { if (n < 0 || n > 10000000) abort(); }
static void mci_string(const char* s) {
    if (!s) { fputs("null", stdout); return; }
    putchar('"');
    for (const unsigned char* p = (const unsigned char*)s; *p; p++) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", (unsigned)*p);
        else putchar(*p);
    }
    putchar('"');
}
static void mci_ints(const int* a, int n) {
    mci_size(n); if (n && !a) abort(); putchar('[');
    for (int i=0; i<n; i++) { if (i) putchar(','); printf("%d", a[i]); }
    putchar(']');
}
static void mci_rows(int** a, int n, const int* sizes) {
    mci_size(n); if (n && (!a || !sizes)) abort(); putchar('[');
    for (int i=0; i<n; i++) { if (i) putchar(','); mci_ints(a[i], sizes[i]); }
    putchar(']');
}
static void mci_strings(char** a, int n) {
    mci_size(n); if (n && !a) abort(); putchar('[');
    for (int i=0; i<n; i++) { if (i) putchar(','); mci_string(a[i]); }
    putchar(']');
}
static void mci_begin(int c, int op) {
    printf("MCIBENCH_OUTPUT_V1 {\"case\":%d,\"op\":%d,\"value\":", c, op);
}
static void mci_end(void) { puts("}"); fflush(stdout); }
'''


def _emit(i, op, typ, value='_got', size=None, columns=None):
    typ = typ.replace('const', '').strip()
    if typ == 'void':
        stmt = 'fputs("null", stdout);'
    elif typ == 'bool':
        stmt = f'fputs({value} ? "true" : "false", stdout);'
    elif typ in ('int', 'long', 'long long'):
        stmt = f'printf("%lld", (long long){value});'
    elif typ in ('double', 'float'):
        stmt = f'if (!isfinite({value})) abort(); printf("%.17g", (double){value});'
    elif typ == 'char*':
        stmt = f'mci_string({value});'
    elif typ in ('int*', 'char**', 'int**') and size is not None:
        if typ == 'int**' and columns is None:
            raise UnsupportedProblemError('C matrix result requires column sizes')
        stmt = (f'mci_rows({value}, {size}, {columns});' if typ == 'int**' else
                f'{"mci_ints" if typ == "int*" else "mci_strings"}({value}, {size});')
    else:
        raise UnsupportedProblemError('C output shape unsupported: ' + typ)
    return f'mci_begin({i}, {op}); {stmt} mci_end();\n'


def _design_args(ctypes, values):
    from local.harness.render import _esc
    declarations, args = [], []
    position = 0
    j = 0
    while j < len(ctypes):
        typ = ctypes[j]
        name = f'_a{j}'
        if typ == 'int*out':
            declarations.append('int _retSize = 0;')
            args.append('&_retSize')
        else:
            value = values[position]
            position += 1
            if typ == 'int*':
                declarations.append(f'int {name}[] = {{{", ".join(str(int(x)) for x in value) or "0"}}};')
                args.append(name)
                if j + 1 >= len(ctypes) or ctypes[j+1] != 'int':
                    raise UnsupportedProblemError('C design array requires size parameter')
                args.append(str(len(value)))
                j += 1
            elif typ == 'char*':
                declarations.append(f'char {name}[] = "{_esc(value)}";')
                args.append(name)
            elif typ == 'int':
                declarations.append(f'int {name} = {int(value)};')
                args.append(name)
            else:
                raise UnsupportedProblemError('C design input unsupported: ' + typ)
        j += 1
    if position != len(values):
        raise ValueError('C design argument count mismatch')
    return '\n'.join(declarations) + '\n', args


def render_c_output(sig, entry, inputs, user_code):
    from local.harness.render import PRELUDE, render_c_arguments, DESIGN_OPS
    parts = [PRELUDE['c'], SERIALIZER, user_code, '\nint main(void) {\n']
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        size = next((p.name for p in entry['c_params'] if p.is_out and p.ctype == 'int*'), None)
        columns = next((p.name for p in entry['c_params'] if p.is_out and p.ctype == 'int**'), None)
        for i, case in enumerate(inputs):
            decls, args = render_c_arguments(entry, case['args'])
            parts.extend(['{\n', '\n'.join(decls), '\n',
                          f'{entry["c_ret"]} _got = {entry["method_name"]}({", ".join(args)});\n',
                          _emit(i, 0, entry['c_ret'], size=size, columns=columns), '}\n'])
    else:
        table = next((t['c']['ops'] for t in DESIGN_OPS.values() if sig.class_name in t['c']['ops']), None)
        if table is None:
            raise UnsupportedProblemError('C design operation table missing')
        for i, case in enumerate(inputs):
            if not case['ops'] or case['ops'][0] != sig.class_name or len(case['ops']) != len(case['args']):
                raise ValueError('invalid design operation plan')
            parts.append('{\n')
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                name, mode, ret, ctypes = table[op]
                declarations, args = _design_args(ctypes, values)
                if mode == 'cctor':
                    parts.extend([declarations, f'{ret} _obj = {name}({", ".join(args)});\n', _emit(i, j, 'void')])
                else:
                    call = f'{name}({", ".join(["_obj"] + args)})'
                    parts.extend(['{\n', declarations,
                                  (call + ';\n') if ret == 'void' else f'{ret} _got = {call};\n',
                                  _emit(i, j, ret, size='_retSize' if 'int*out' in ctypes else None), '}\n'])
            parts.append('}\n')
    parts.append('return 0;\n}\n')
    return ''.join(parts)
