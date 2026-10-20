"""C# input-only driver with standard JSON return serialization."""
from local.harness.typespec import PlainSig, UnsupportedProblemError


def render_csharp_output(sig, entry, inputs, user_code):
    from local.harness.render import PRELUDE, clean_cs_user_code, _arg_expr, _cs_val
    usings, code = clean_cs_user_code(user_code)
    parts = [PRELUDE['csharp'], '\n'.join(usings), '\n', code, r'''
public class Judge {
    static void Emit(int c, int op, object value) {
        Console.WriteLine("MCIBENCH_OUTPUT_V1 " + System.Text.Json.JsonSerializer.Serialize(
            new { @case = c, op = op, value = value }));
    }
    public static void Main(string[] args) {
''']
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        for i, case in enumerate(inputs):
            args = ', '.join(_arg_expr('csharp', entry, sig, j, case['args'][p.name])
                             for j, p in enumerate(sig.params))
            parts.append(f'{{ var sol = new Solution(); var got = sol.{entry["method_name"]}({args}); Emit({i}, 0, got); }}\n')
    else:
        methods = {name: (params, ret) for name, params, ret in sig.methods}
        for i, case in enumerate(inputs):
            if not case['ops'] or case['ops'][0] != sig.class_name or len(case['ops']) != len(case['args']):
                raise ValueError('invalid design operation plan')
            parts.append('{\n')
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                params, ret = methods['__init__' if op == sig.class_name else op]
                if len(params) != len(values):
                    raise ValueError('design argument count mismatch')
                args = ', '.join(_cs_val(v, p.typ) for p, v in zip(params, values))
                if op == sig.class_name:
                    parts.append(f'var obj = new {sig.class_name}({args});\n')
                    value = 'null'
                else:
                    method = op[0].upper() + op[1:]
                    call = f'obj.{method}({args})'
                    if ret is None:
                        parts.append(call + ';\n')
                        value = 'null'
                    else:
                        value = call
                parts.append(f'Emit({i}, {j}, {value});\n')
            parts.append('}\n')
    parts.append('}\n}\n')
    return ''.join(parts)
