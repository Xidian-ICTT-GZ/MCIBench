"""Java output driver with encoded inputs, excluding all expected answers."""
import re
from local.harness.typespec import PlainSig, UnsupportedProblemError

SERIALIZER = r'''
    static String json(Object v) {
        if (v == null) return "null";
        if (v instanceof String || v instanceof Character) {
            StringBuilder b = new StringBuilder("\"");
            for (char c : v.toString().toCharArray()) {
                if (c == '"' || c == '\\') b.append('\\').append(c);
                else if (c < 32 || Character.isSurrogate(c)) b.append(String.format("\\u%04x", (int)c));
                else b.append(c);
            }
            return b.append('"').toString();
        }
        if (v instanceof Boolean) return v.toString();
        if (v instanceof Number) {
            if ((v instanceof Double && !Double.isFinite((Double)v)) ||
                (v instanceof Float && !Float.isFinite((Float)v)))
                throw new IllegalArgumentException("non-finite return");
            return v.toString();
        }
        StringBuilder b = new StringBuilder("[");
        if (v.getClass().isArray()) {
            int n = java.lang.reflect.Array.getLength(v);
            for (int i=0; i<n; i++) {
                if (i>0) b.append(',');
                b.append(json(java.lang.reflect.Array.get(v, i)));
            }
        } else if (v instanceof Iterable) {
            boolean first = true;
            for (Object item : (Iterable<?>)v) {
                if (!first) b.append(','); first = false; b.append(json(item));
            }
        } else throw new IllegalArgumentException("unsupported return shape");
        return b.append(']').toString();
    }
    static void emit(int c, int op, Object v) {
        System.out.println("MCIBENCH_OUTPUT_V1 {\"case\":"+c+",\"op\":"+op+",\"value\":"+json(v)+"}");
    }
'''


def render_java_output(sig, entry, inputs, user_code):
    from local.harness import dataio
    from local.harness.render import PRELUDE, hoist_java_imports, _java_array_type
    imports, code = hoist_java_imports(user_code)
    code = re.sub(r'\bpublic\s+class\b', 'class', code)
    tokens, blocks = [], []
    def read_args(params, values, types):
        if len(params) != len(values) or len(params) != len(types):
            raise ValueError('Java argument count mismatch')
        statements, names = [], []
        for k, (p, val, typ) in enumerate(zip(params, values, types)):
            reader = 'rds().charAt(0)' if typ == 'char' else dataio.JAVA_READERS.get(typ)
            if reader is None or typ in ('boolean[]', 'double[]'):
                raise UnsupportedProblemError('Java input reader unavailable: ' + typ)
            dataio._enc_value(val, p.typ, tokens)
            name = f'_a{k}'
            statements.append(f'{dataio._java_decl(typ)} {name} = {reader};\n')
            names.append(name)
        return ''.join(statements), ', '.join(names)
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        template = None
        for case in inputs:
            decls, args = read_args(sig.params, [case['args'][p.name] for p in sig.params], entry['param_types'])
            template = decls + f'Solution sol = new Solution(); emit(i, 0, sol.{entry["method_name"]}({args}));\n'
        blocks.append(f'static void run() {{ for (int i=0; i<{len(inputs)}; i++) {{\n' + (template or '') + '} }\n')
        calls = 'run();'
    else:
        methods = {name: (params, ret) for name, params, ret in sig.methods}
        for i, case in enumerate(inputs):
            if not case['ops'] or case['ops'][0] != sig.class_name or len(case['ops']) != len(case['args']):
                raise ValueError('invalid design operation plan')
            body = [f'static void run{i}() {{\n{sig.class_name} obj = null;\n']
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                params, ret = methods['__init__' if op == sig.class_name else op]
                decls, args = read_args(params, values, [_java_array_type(p.typ) for p in params])
                body.extend(['{\n', decls])
                if op == sig.class_name:
                    body.append(f'obj = new {sig.class_name}({args});\n')
                    value = 'null'
                elif ret is None:
                    body.append(f'obj.{op}({args});\n')
                    value = 'null'
                else:
                    value = f'obj.{op}({args})'
                body.append(f'emit({i}, {j}, {value});\n}}\n')
            body.append('}\n')
            blocks.append(''.join(body))
        calls = '\n'.join(f'run{i}();' for i in range(len(inputs)))
    encoded = ' '.join(tokens)
    return (PRELUDE['java'] + '\n'.join(imports) + '\n' + code + '\npublic class Judge {\n'
            + SERIALIZER + dataio.data_decl('java', encoded) + dataio.reader_source('java', encoded)
            + ''.join(blocks) + 'public static void main(String[] args) { __initRd(__ENC);\n'
            + calls + '\n}\n}\n')
