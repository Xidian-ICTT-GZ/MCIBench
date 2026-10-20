"""Rust input-only encoded driver and JSON serialization without external crates."""
from local.harness.typespec import PlainSig, UnsupportedProblemError

SERIALIZER = r'''
trait MciJson { fn json(&self) -> String; }
impl MciJson for str {
    fn json(&self) -> String {
        let mut s = String::from("\"");
        for c in self.chars() {
            match c {
                '"' => s.push_str("\\\""), '\\' => s.push_str("\\\\"),
                c if (c as u32) < 32 => s.push_str(&format!("\\u{:04x}", c as u32)),
                c => s.push(c),
            }
        }
        s.push('"'); s
    }
}
impl MciJson for String { fn json(&self) -> String { self.as_str().json() } }
impl MciJson for bool { fn json(&self) -> String { self.to_string() } }
impl MciJson for () { fn json(&self) -> String { "null".into() } }
macro_rules! mci_int { ($($t:ty),*) => { $(impl MciJson for $t {
    fn json(&self) -> String { self.to_string() }
})* }; }
mci_int!(i8, i16, i32, i64, isize, u8, u16, u32, u64, usize);
macro_rules! mci_float { ($($t:ty),*) => { $(impl MciJson for $t {
    fn json(&self) -> String { assert!(self.is_finite(), "non-finite output"); self.to_string() }
})* }; }
mci_float!(f32, f64);
impl<T: MciJson> MciJson for Vec<T> {
    fn json(&self) -> String {
        format!("[{}]", self.iter().map(|v| v.json()).collect::<Vec<_>>().join(","))
    }
}
fn mci_emit<T: MciJson>(c: usize, op: usize, v: &T) {
    use std::io::Write;
    println!("MCIBENCH_OUTPUT_V1 {{\"case\":{},\"op\":{},\"value\":{}}}", c, op, v.json());
    std::io::stdout().flush().unwrap();
}
'''


def render_rust_output(sig, entry, inputs, user_code):
    from local.harness import dataio
    from local.harness.render import PRELUDE, _rust_type_name
    tokens, body = [], []
    def args(params, values, types):
        if len(params) != len(values) or len(params) != len(types):
            raise ValueError('Rust argument count mismatch')
        reads = []
        for p, v, typ in zip(params, values, types):
            reader = ('rd.s().chars().next().expect("character input")' if typ == 'char'
                      else dataio.RUST_READERS.get(typ))
            if reader is None:
                raise UnsupportedProblemError('Rust encoded input unsupported: ' + typ)
            dataio._enc_value(v, p.typ, tokens)
            reads.append(reader)
        return ', '.join(reads)
    if isinstance(sig, PlainSig):
        if sig.ret is None:
            raise UnsupportedProblemError('void plain output requires a mutation contract')
        types = [p[1] if isinstance(p, (tuple, list)) else p for p in entry['rust_params']]
        call = ''
        for case in inputs:
            call = args(sig.params, [case['args'][p.name] for p in sig.params], types)
        body.append(f'for i in 0..{len(inputs)} {{ let got = Solution::{entry["method_name"]}({call}); mci_emit(i, 0, &got); }}\n')
    else:
        methods = {name: (params, ret) for name, params, ret in sig.methods}
        for i, case in enumerate(inputs):
            if not case['ops'] or case['ops'][0] != sig.class_name or len(case['ops']) != len(case['args']):
                raise ValueError('invalid design operation plan')
            body.append('{\n')
            for j, (op, values) in enumerate(zip(case['ops'], case['args'])):
                params, ret = methods['__init__' if op == sig.class_name else op]
                call_args = args(params, values, [_rust_type_name(p.typ) for p in params])
                if op == sig.class_name:
                    body.append(f'let mut obj = {sig.class_name}::new({call_args});\n')
                    value = '()'
                elif ret is None:
                    body.append(f'obj.{op}({call_args});\n')
                    value = '()'
                else:
                    value = f'obj.{op}({call_args})'
                body.append(f'mci_emit({i}, {j}, &({value}));\n')
            body.append('}\n')
    encoded = ' '.join(tokens)
    return (PRELUDE['rust'] + SERIALIZER + dataio.data_decl('rust', encoded)
            + dataio.reader_source('rust', encoded) + user_code + '\nfn main() {\n'
            + 'let mut rd = _Rd::new(__ENC);\n' + ''.join(body) + '}\n')
