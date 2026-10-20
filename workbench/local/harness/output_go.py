"""Go input-only driver, preserving explicitly declared import aliases."""
from local.harness.typespec import PlainSig, UnsupportedProblemError


def render_go_output(sig, entry, inputs, user_code):
    from local.harness.render import (harvest_go_imports, clean_go_user_code,
                                      _GO_USER_PKG_MARKERS, _arg_expr, value_expr)
    specs = harvest_go_imports(user_code)
    code = clean_go_user_code(user_code)
    if not specs:
        specs = [spec for spec, marker in _GO_USER_PKG_MARKERS if marker in code]
        # LeetCode snippets omit imports, including packages used by the driver.
        # Preserve the conventional user names instead of aliasing these away.
        for path in ('fmt', 'os', 'reflect', 'encoding/json'):
            name = path.rsplit('/', 1)[-1]
            if name + '.' in code and f'"{path}"' not in specs:
                specs.append(f'"{path}"')
    # The driver uses the same alias as an existing user import. Blank imports
    # can safely become named; dot imports need unqualified function names.
    def require(path, fallback):
        for i, spec in enumerate(specs):
            if spec.split('"')[1] == path:
                alias = spec.split('"')[0].strip() or path.rsplit('/', 1)[-1]
                if alias == '_':
                    specs[i] = fallback + ' "' + path + '"'
                    alias = fallback
                return '' if alias == '.' else alias + '.'
        specs.append(f'{fallback} "{path}"')
        return fallback + '.'
    fmt = require('fmt', '_mci_fmt')
    js = require('encoding/json', '_mci_json')
    reflect = require('reflect', '_mci_reflect')
    parts = ['package main\nimport (\n', '\n'.join(specs), '\n)\n', code, '\n',
             'func _mci_normalize(value interface{}) interface{} {\n',
             'if value == nil { return nil }\n',
             f'v := {reflect}ValueOf(value)\n',
             f'if v.Kind() == {reflect}Slice || v.Kind() == {reflect}Array {{\n',
             'out := make([]interface{}, v.Len())\n',
             'for i := range out { out[i] = _mci_normalize(v.Index(i).Interface()) }\n',
             'return out\n}\nreturn value\n}\n',
             'func _mci_emit(c int, op int, value interface{}) {\n',
             f'data, err := {js}Marshal(map[string]interface{{}}{{"case":c,"op":op,"value":_mci_normalize(value)}})\n',
             'if err != nil { panic(err) }\n',
             f'{fmt}Println("MCIBENCH_OUTPUT_V1 " + string(data))\n',
             '}\nfunc main() {\n']
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        for i, case in enumerate(inputs):
            args = ', '.join(_arg_expr('golang', entry, sig, j, case['args'][p.name])
                             for j, p in enumerate(sig.params))
            parts.append(f'{{ got := {entry["method_name"]}({args}); _mci_emit({i}, 0, got) }}\n')
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
                args = ', '.join(value_expr('golang', v, p.typ) for p, v in zip(params, values))
                if op == sig.class_name:
                    parts.append(f'obj := Constructor({args})\n_ = obj\n')
                    value = 'nil'
                else:
                    call = f'obj.{op[0].upper() + op[1:]}({args})'
                    if ret is None:
                        parts.append(call + '\n')
                        value = 'nil'
                    else:
                        value = call
                parts.append(f'_mci_emit({i}, {j}, {value})\n')
            parts.append('}\n')
    parts.append('}\n')
    return ''.join(parts)
