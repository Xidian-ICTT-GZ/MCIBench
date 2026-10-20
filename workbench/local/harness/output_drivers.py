"""Return-value-only drivers. No expected answers or verdict code in the sandbox.

Adapters are explicitly enumerated during migration; unsupported languages raise
instead of silently using the old self-reporting completion protocol.
"""
from __future__ import annotations

import json
from local.harness.output_protocol import PREFIX
from local.harness.typespec import PlainSig, DesignSig, UnsupportedProblemError

OUTPUT_LANGUAGES = frozenset({'python3', 'javascript', 'cpp', 'csharp', 'golang', 'java', 'rust', 'c'})


def render_output_driver(lang: str, sig: PlainSig | DesignSig, entry: dict,
                         cases: list[dict], user_code: str) -> str:
    from local.harness.render import PRELUDE, _py_repr, _arg_expr, _CALL, _OBJ_NEW
    if lang not in OUTPUT_LANGUAGES:
        raise UnsupportedProblemError(f'External output protocol adapter not implemented: {lang}')
    # Deliberately project only inputs. Do not touch expected/votes/checker data.
    inputs = [{k: c[k] for k in ('args', 'ops') if k in c} for c in cases]
    if lang == 'cpp':
        from local.harness.output_cpp import render_cpp_output
        return render_cpp_output(sig, entry, inputs, user_code)
    if lang == 'csharp':
        from local.harness.output_csharp import render_csharp_output
        return render_csharp_output(sig, entry, inputs, user_code)
    if lang == 'golang':
        from local.harness.output_go import render_go_output
        return render_go_output(sig, entry, inputs, user_code)
    if lang == 'java':
        from local.harness.output_java import render_java_output
        return render_java_output(sig, entry, inputs, user_code)
    if lang == 'rust':
        from local.harness.output_rust import render_rust_output
        return render_rust_output(sig, entry, inputs, user_code)
    if lang == 'c':
        from local.harness.output_c import render_c_output
        return render_c_output(sig, entry, inputs, user_code)
    if lang == 'python3':
        parts = [PRELUDE[lang], 'import json as _output_json\n', user_code.rstrip() + '\n']
        def emit(case, op, value):
            return f'print({PREFIX!r} + _output_json.dumps({{"case":{case},"op":{op},"value":{value}}}, ensure_ascii=True, allow_nan=False), flush=True)\n'
    else:
        from local.harness.output_javascript import helpers
        parts = [PRELUDE[lang], helpers(user_code), user_code.rstrip() + '\n']
        def emit(case, op, value):
            # JSON.stringify serializes undefined as a missing key; the host
            # rejects that malformed envelope rather than treating it as null.
            return f'console.log({json.dumps(PREFIX)} + _mci_json({{case:{case},op:{op},value:{value}}}));\n'
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('Void/mutating plain methods require a distinct output contract')
        for i, case in enumerate(inputs):
            if lang == 'python3':
                args = ', '.join(_py_repr(case['args'][p.name]) for p in sig.params)
                parts.extend([_OBJ_NEW[lang], _CALL[lang].format(m=entry['method_name'], args=args), emit(i, 0, '_got')])
            else:
                args = ', '.join(_arg_expr(lang, entry, sig, j, case['args'][p.name]) for j, p in enumerate(sig.params))
                parts.extend(['{\n', _OBJ_NEW.get(lang, ''), _CALL[lang].format(m=entry['method_name'], args=args), emit(i, 0, '_got'), '}\n'])
    else:
        methods = {name: (params, ret) for name, params, ret in sig.methods}
        for i, case in enumerate(inputs):
            if len(case['ops']) != len(case['args']):
                raise ValueError('design operations and arguments differ in length')
            if lang == 'javascript':
                parts.append('{ let _obj;\n')
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                args = ', '.join(_py_repr(v) if lang == 'python3' else json.dumps(v, ensure_ascii=True) for v in values)
                if op == sig.class_name:
                    parts.append(f'_obj = {sig.class_name}({args})\n' if lang == 'python3' else f'_obj = new {sig.class_name}({args});\n')
                    parts.append(emit(i, j, 'None' if lang == 'python3' else 'null'))
                elif methods[op][1] is None:
                    parts.append(f'_obj.{op}({args})' + ('\n' if lang == 'python3' else ';\n'))
                    parts.append(emit(i, j, 'None' if lang == 'python3' else 'null'))
                else:
                    parts.append(emit(i, j, f'_obj.{op}({args})'))
            if lang == 'javascript':
                parts.append('}\n')
    return ''.join(parts)
