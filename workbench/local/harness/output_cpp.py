"""C++ return serialization and input-only invocation drivers."""
from local.harness.typespec import PlainSig, UnsupportedProblemError

SERIALIZER = r'''
#include <type_traits>
#include <stdexcept>
namespace mcibench_output {
inline void string_value(const std::string& s) {
    std::cout << '"';
    const char* hex = "0123456789abcdef";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') std::cout << '\\' << c;
        else if (c < 32) std::cout << "\\u00" << hex[c >> 4] << hex[c & 15];
        else std::cout << c;
    }
    std::cout << '"';
}
template<class T> void value(const T& v) {
    if constexpr (std::is_same_v<T, std::string>) string_value(v);
    else if constexpr (std::is_same_v<T, bool>) std::cout << (v ? "true" : "false");
    else if constexpr (std::is_integral_v<T>) std::cout << v;
    else if constexpr (std::is_floating_point_v<T>) {
        if (!std::isfinite(v)) throw std::runtime_error("non-finite return value");
        std::cout << std::setprecision(std::numeric_limits<T>::max_digits10) << v;
    } else {
        std::cout << '[';
        bool first = true;
        for (const auto& item : v) {
            if (!first) std::cout << ',';
            first = false;
            value(item);
        }
        std::cout << ']';
    }
}
inline void value(std::nullptr_t) { std::cout << "null"; }
template<class T> void emit(int c, int op, const T& v) {
    std::cout << "MCIBENCH_OUTPUT_V1 {\"case\":" << c << ",\"op\":" << op << ",\"value\":";
    value(v);
    std::cout << '}' << std::endl;
}
}
'''


def render_cpp_output(sig, entry, inputs, user_code):
    from local.harness.render import PRELUDE, _arg_expr, _cpp_type, _cpp_val, _cpp_decl_type
    parts = [PRELUDE['cpp'], SERIALIZER, user_code, '\nint main() {\n']
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        for i, case in enumerate(inputs):
            parts.append('{\n')
            for j, p in enumerate(sig.params):
                types = entry.get('param_types') or []
                typ = _cpp_decl_type(types[j]) if j < len(types) else _cpp_type(p.typ)
                parts.append(f'{typ} _a{j} = {_arg_expr("cpp", entry, sig, j, case["args"][p.name])};\n')
            args = ', '.join(f'_a{j}' for j in range(len(sig.params)))
            parts.append(f'Solution sol; auto _got = sol.{entry["method_name"]}({args});\n')
            parts.append(f'mcibench_output::emit({i}, 0, _got);\n}}\n')
    else:
        methods = {name: (params, ret) for name, params, ret in sig.methods}
        for i, case in enumerate(inputs):
            parts.append('{\n')
            if not case['ops'] or case['ops'][0] != sig.class_name or len(case['ops']) != len(case['args']):
                raise ValueError('invalid design operation plan')
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                params, ret = methods['__init__' if op == sig.class_name else op]
                if len(params) != len(values):
                    raise ValueError('design argument count mismatch')
                names = []
                for k, (param, v) in enumerate(zip(params, values)):
                    name = f'_arg_{j}_{k}'
                    parts.append(f'{_cpp_type(param.typ)} {name} = {_cpp_val(v, param.typ)};\n')
                    names.append(name)
                args = ', '.join(names)
                if op == sig.class_name:
                    parts.append(f'{sig.class_name} _obj{{{args}}};\n')
                    value = 'nullptr'
                elif ret is None:
                    parts.append(f'_obj.{op}({args});\n')
                    value = 'nullptr'
                else:
                    value = f'_obj.{op}({args})'
                parts.append(f'mcibench_output::emit({i}, {j}, {value});\n')
            parts.append('}\n')
    parts.append('return 0;\n}\n')
    return ''.join(parts)
