"""Input-only JSON function adapters, using the existing eight-language sandbox.

No expected values, oracle code or verdict logic enters these programs. These
adapters extend the lab without changing the frozen historical judge closure.
"""
import json
import re
from local.lab import source_guard
source_guard.register(__file__)

VERSION='portable-json-functions-v1'

CONTRACTS={
 'python3':'Implement def solve(data: dict): returning a JSON value. Standard Python libraries are available. No main or input/output code.',
 'javascript':'Implement function solve(data) returning a JSON value. No main or console output. JavaScript standard library is available.',
 'cpp':'''Implement Mci solve(Mci data). No main or includes. Available: using namespace std; STL; Mci JSON class.
Mci supports null, bool, long long, double, string, Mci::Arr (vector<Mci>), Mci::Obj (map<string,Mci>).
Read data["key"], data[index], .integer(), .number(), .text(), .boolean(), .array(), .object(), .size().
Type checks: .is_null(), .is_array(), .is_object(), .is_string(), .is_integer(), .is_number(), .is_boolean().
Return Mci(42LL), Mci("text"), Mci(true), Mci(nullptr), Mci(Mci::Arr{...}), Mci(Mci::Obj{{"key",value}}).
Do not use nlohmann/json or external libraries.''',
 'c':'''Implement Mci* solve(Mci* data). No main or includes. Standard C library is available.
Read mci_get(data,"key"), mci_at(array,index), mci_len(value), mci_int(value), mci_num(value), mci_str(value), mci_truth(value).
Construct with mci_integer(long long), mci_number(double), mci_string(const char*), mci_boolean(bool), mci_null(), mci_array(), mci_object().
Use mci_push(array,value) and mci_set(object,"key",value). The Mci struct is supplied by the platform. No external JSON library.''',
 'java':'''Implement class Solution { public Object solve(Map<String,Object> data) { ... } }. No public class or main.
JSON numbers arrive as Long or Double; arrays as List<Object>, objects as Map<String,Object>. Return JSON-compatible objects.
Helpers: Mci.num(Object)->long, Mci.real(Object)->double, Mci.arr(Object)->List<Object>, Mci.obj(Object)->Map<String,Object>,
Mci.map(Object... alternatingKeysValues)->Map<String,Object>. java.util.*, java.math.*, java.time.*, java.util.regex.* are imported.''',
 'csharp':'''Implement public class Solution { public object Solve(System.Text.Json.JsonElement data) { ... } }.
No Main. Read JSON using GetProperty, GetInt64, GetString, EnumerateArray. Return primitive, arrays, dictionaries or anonymous objects.
Standard System, Collections.Generic, Linq, Text, Text.Json, Numerics and Globalization namespaces are imported.''',
 'golang':'''Implement func solve(data map[string]interface{}) interface{}. No package, import or main.
JSON integers arrive as int64; arrays []interface{}; objects map[string]interface{}. Helpers MciInt(interface{}) int64, MciArr(interface{}) []interface{}, MciObj(interface{}) map[string]interface{}.
Available imported packages: fmt, math, math/bits (bits), sort, strings, strconv, container/heap (heap), container/list (list), regexp, encoding/json, time.
Return a JSON-compatible value. Named helper functions/types are allowed.''',
 'rust':'''Implement fn solve(data: Mci) -> Mci. No main or external crates. std library is available.
Mci enum variants: Null, Bool(bool), Int(i64), Float(f64), Str(String), Array(Vec<Mci>), Object(BTreeMap<String,Mci>).
Read data["key"], data[index], .integer(), .number(), .text(), .boolean(), .array(), .object(), .len().
Mci is Clone. BTreeMap, HashMap, HashSet, BTreeSet, VecDeque, BinaryHeap are imported. Return a Mci value. No serde_json.''',
 'mysql':'Return only one executable native MySQL 8.0 SQL statement. Tables with the statement types and explicit primary keys are initialized by the platform. Do not create schema or embed test data. Scalar input parameters are session variables @parameter. For q177 use the native CREATE FUNCTION getNthHighestSalary(N INT) RETURNS INT interface; the platform calls it with the scalar n input. For mutation tasks return the required DELETE/UPDATE statement; the platform judges the final table.',
 'sqlite':'Return only an executable SQLite SQL statement. Named scalar input parameters use :parameter. Tables are initialized by the platform. Do not create schema or embed test data.',
 'bash':'Return only a Bash script. Input files are provided in the current directory with their specified filenames. Write the requested answer to stdout. No test data or expected answers in the script.'}

CPP=r'''
#include <bits/stdc++.h>
using namespace std;
struct Mci {
 using Arr=vector<Mci>; using Obj=map<string,Mci>;
 variant<nullptr_t,bool,long long,double,string,Arr,Obj> v;
 Mci():v(nullptr){} Mci(nullptr_t):v(nullptr){} Mci(bool x):v(x){}
 Mci(int x):v((long long)x){} Mci(long long x):v(x){} Mci(double x):v(x){}
 Mci(const char*x):v(string(x)){} Mci(string x):v(move(x)){} Mci(Arr x):v(move(x)){} Mci(Obj x):v(move(x)){}
 bool is_null() const{return holds_alternative<nullptr_t>(v);}
 bool is_array() const{return holds_alternative<Arr>(v);} bool is_object() const{return holds_alternative<Obj>(v);}
 bool is_string() const{return holds_alternative<string>(v);} bool is_integer() const{return holds_alternative<long long>(v);}
 bool is_number() const{return is_integer()||holds_alternative<double>(v);} bool is_boolean() const{return holds_alternative<bool>(v);}
 long long integer() const{return get<long long>(v);} double number()const{return holds_alternative<long long>(v)?(double)integer():get<double>(v);}
 const string& text()const{return get<string>(v);} bool boolean()const{return get<bool>(v);}
 Arr& array(){return get<Arr>(v);} const Arr& array()const{return get<Arr>(v);}
 Obj& object(){return get<Obj>(v);} const Obj& object()const{return get<Obj>(v);}
 Mci& operator[](const string&k){return object().at(k);} const Mci& operator[](const string&k)const{return object().at(k);}
 Mci& operator[](size_t i){return array().at(i);} const Mci& operator[](size_t i)const{return array().at(i);}
 size_t size()const{if(holds_alternative<Arr>(v))return array().size();if(holds_alternative<Obj>(v))return object().size();return text().size();}
};
static void mci_quote(const string&s){cout<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')cout<<'\\'<<c;else if(c<32){char b[7];snprintf(b,7,"\\u%04x",c);cout<<b;}else cout<<c;}cout<<'"';}
static void mci_emit(const Mci&x){switch(x.v.index()){
 case 0:cout<<"null";break;case 1:cout<<(x.boolean()?"true":"false");break;case 2:cout<<x.integer();break;
 case 3:if(!isfinite(x.number()))throw runtime_error("nonfinite JSON");cout<<setprecision(17)<<x.number();break;
 case 4:mci_quote(x.text());break;case 5:{cout<<'[';bool first=true;for(auto&v:x.array()){if(!first)cout<<',';first=false;mci_emit(v);}cout<<']';break;}
 case 6:{cout<<'{';bool first=true;for(auto&p:x.object()){if(!first)cout<<',';first=false;mci_quote(p.first);cout<<':';mci_emit(p.second);}cout<<'}';break;}}}
'''

C=r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>
#include <math.h>
typedef struct Mci {int type;long long i;double d;char*s;size_t n;struct Mci**a;char**keys;} Mci;
static Mci* mci_new(int t){Mci*x=calloc(1,sizeof(Mci));if(!x)abort();x->type=t;return x;}
static Mci* mci_null(){return mci_new(0);} static Mci* mci_integer(long long v){Mci*x=mci_new(2);x->i=v;return x;}
static Mci* mci_number(double v){Mci*x=mci_new(3);x->d=v;return x;}static Mci* mci_boolean(bool v){Mci*x=mci_new(1);x->i=v;return x;}
static Mci* mci_string_n(const char*v,size_t n){Mci*x=mci_new(4);x->s=malloc(n+1);if(!x->s)abort();memcpy(x->s,v,n);x->s[n]=0;x->n=n;return x;}
static Mci* mci_string(const char*v){return mci_string_n(v,strlen(v));}
static Mci* mci_array(){return mci_new(5);}static Mci* mci_object(){return mci_new(6);}
static size_t mci_len(Mci*x){return x->n;}static long long mci_int(Mci*x){if(x->type!=2)abort();return x->i;}
static double mci_num(Mci*x){if(x->type!=2&&x->type!=3)abort();return x->type==2?(double)x->i:x->d;}
static const char* mci_str(Mci*x){if(x->type!=4)abort();return x->s;}static bool mci_truth(Mci*x){if(x->type!=1)abort();return x->i;}
static Mci* mci_at(Mci*x,size_t i){if(x->type!=5||i>=x->n)abort();return x->a[i];}
static Mci* mci_get(Mci*x,const char*k){if(x->type!=6)abort();for(size_t i=0;i<x->n;i++)if(!strcmp(x->keys[i],k))return x->a[i];abort();}
static void mci_push(Mci*x,Mci*v){if(x->type!=5&&x->type!=6)abort();x->a=realloc(x->a,(x->n+1)*sizeof(Mci*));if(!x->a)abort();x->a[x->n++]=v;}
static void mci_set(Mci*x,const char*k,Mci*v){if(x->type!=6)abort();for(size_t i=0;i<x->n;i++)if(!strcmp(x->keys[i],k)){x->a[i]=v;return;}
 x->keys=realloc(x->keys,(x->n+1)*sizeof(char*));if(!x->keys)abort();x->keys[x->n]=strdup(k);mci_push(x,v);}
static void mci_quote_n(const char*s,size_t n){putchar('"');for(size_t i=0;i<n;i++){unsigned char c=(unsigned char)s[i];if(c=='"'||c=='\\')printf("\\%c",c);else if(c<32)printf("\\u%04x",c);else putchar(c);}putchar('"');}
static void mci_quote(const char*s){mci_quote_n(s,strlen(s));}
static void mci_emit(Mci*x){if(!x)abort();switch(x->type){case 0:printf("null");break;case 1:printf(x->i?"true":"false");break;
 case 2:printf("%lld",x->i);break;case 3:if(!isfinite(x->d))abort();printf("%.17g",x->d);break;case 4:mci_quote_n(x->s,x->n);break;
 case 5:case 6:putchar(x->type==5?'[':'{');for(size_t i=0;i<x->n;i++){if(i)putchar(',');if(x->type==6){mci_quote(x->keys[i]);putchar(':');}mci_emit(x->a[i]);}putchar(x->type==5?']':'}');break;default:abort();}}
'''

RUST=r'''
use std::collections::{BTreeMap,HashMap,HashSet,BTreeSet,VecDeque,BinaryHeap};
#[derive(Clone,Debug)]
pub enum Mci {Null,Bool(bool),Int(i64),Float(f64),Str(String),Array(Vec<Mci>),Object(BTreeMap<String,Mci>)}
impl Mci {
pub fn integer(&self)->i64{if let Mci::Int(x)=self{*x}else{panic!("integer required")}}
pub fn number(&self)->f64{match self{Mci::Int(x)=>*x as f64,Mci::Float(x)=>*x,_=>panic!("number required")}}
pub fn text(&self)->&str{if let Mci::Str(x)=self{x}else{panic!("string required")}}
pub fn boolean(&self)->bool{if let Mci::Bool(x)=self{*x}else{panic!("boolean required")}}
pub fn array(&self)->&Vec<Mci>{if let Mci::Array(x)=self{x}else{panic!("array required")}}
pub fn object(&self)->&BTreeMap<String,Mci>{if let Mci::Object(x)=self{x}else{panic!("object required")}}
pub fn len(&self)->usize{match self{Mci::Array(x)=>x.len(),Mci::Object(x)=>x.len(),Mci::Str(x)=>x.chars().count(),_=>panic!("container required")}}
}
impl std::ops::Index<&str> for Mci{type Output=Mci;fn index(&self,k:&str)->&Mci{&self.object()[k]}}
impl std::ops::Index<usize> for Mci{type Output=Mci;fn index(&self,k:usize)->&Mci{&self.array()[k]}}
fn mci_quote(s:&str)->String{let mut o=String::from("\"");for c in s.chars(){match c{'"'=>o.push_str("\\\""),'\\'=>o.push_str("\\\\"),c if (c as u32)<32=>o.push_str(&format!("\\u{:04x}",c as u32)),c=>o.push(c)}}o.push('"');o}
fn mci_json(x:&Mci)->String{match x{Mci::Null=>"null".into(),Mci::Bool(v)=>v.to_string(),Mci::Int(v)=>v.to_string(),Mci::Float(v)=>{assert!(v.is_finite());v.to_string()},Mci::Str(v)=>mci_quote(v),Mci::Array(v)=>format!("[{}]",v.iter().map(mci_json).collect::<Vec<_>>().join(",")),Mci::Object(v)=>format!("{{{}}}",v.iter().map(|(k,v)|format!("{}:{}",mci_quote(k),mci_json(v))).collect::<Vec<_>>().join(","))}}
'''

JAVA=r'''
import java.util.*;import java.math.*;import java.time.*;import java.util.regex.*;
class Mci {
static long num(Object o){return ((Number)o).longValue();}static double real(Object o){return ((Number)o).doubleValue();}
@SuppressWarnings("unchecked") static List<Object> arr(Object o){return (List<Object>)o;}
@SuppressWarnings("unchecked") static Map<String,Object> obj(Object o){return (Map<String,Object>)o;}
static Map<String,Object> map(Object... a){Map<String,Object>m=new LinkedHashMap<>();for(int i=0;i<a.length;i+=2)m.put((String)a[i],a[i+1]);return m;}
static String quote(String s){StringBuilder b=new StringBuilder("\"");for(int i=0;i<s.length();i++){char c=s.charAt(i);if(c=='"'||c=='\\')b.append('\\').append(c);else if(c<32)b.append(String.format("\\u%04x",(int)c));else b.append(c);}return b.append('"').toString();}
static String json(Object x){if(x==null)return "null";if(x instanceof String)return quote((String)x);if(x instanceof Boolean)return x.toString();
if(x instanceof Number){double n=((Number)x).doubleValue();if(!Double.isFinite(n))throw new IllegalArgumentException("nonfinite");return x.toString();}
if(x instanceof Map){StringJoiner j=new StringJoiner(",","{","}");for(Object e0:((Map<?,?>)x).entrySet()){Map.Entry<?,?>e=(Map.Entry<?,?>)e0;j.add(quote((String)e.getKey())+":"+json(e.getValue()));}return j.toString();}
StringJoiner j=new StringJoiner(",","[","]");if(x instanceof Iterable){for(Object a:(Iterable<?>)x)j.add(json(a));}else if(x.getClass().isArray()){for(int i=0;i<java.lang.reflect.Array.getLength(x);i++)j.add(json(java.lang.reflect.Array.get(x,i)));}else throw new IllegalArgumentException("non JSON return");return j.toString();}
// Parse host-authored JSON at runtime so large arrays never overflow javac's
// 64 KiB method/constant limits. Integer values keep their Long type.
static Object parse(String s){Parser p=new Parser(s);Object v=p.value();p.ws();if(p.i!=s.length())throw new IllegalArgumentException("trailing JSON");return v;}
static class Parser {
final String s;int i;Parser(String s){this.s=s;}void ws(){while(i<s.length()&&Character.isWhitespace(s.charAt(i)))i++;}
char take(){if(i>=s.length())throw new IllegalArgumentException("incomplete JSON");return s.charAt(i++);}
String string(){if(take()!='"')throw new IllegalArgumentException("string required");StringBuilder b=new StringBuilder();while(true){char c=take();if(c=='"')return b.toString();if(c=='\\'){c=take();switch(c){case '"':case '\\':case '/':break;case 'b':c='\b';break;case 'f':c='\f';break;case 'n':c='\n';break;case 'r':c='\r';break;case 't':c='\t';break;case 'u':c=(char)Integer.parseInt(s.substring(i,i+4),16);i+=4;break;default:throw new IllegalArgumentException("escape");}}b.append(c);}}
Object value(){ws();char c=s.charAt(i);if(c=='"')return string();
if(c=='{'){i++;Map<String,Object> m=new LinkedHashMap<>();ws();if(s.charAt(i)=='}'){i++;return m;}while(true){ws();String k=string();ws();if(take()!=':')throw new IllegalArgumentException("colon");m.put(k,value());ws();c=take();if(c=='}')return m;if(c!=',')throw new IllegalArgumentException("comma");}}
if(c=='['){i++;List<Object> a=new ArrayList<>();ws();if(s.charAt(i)==']'){i++;return a;}while(true){a.add(value());ws();c=take();if(c==']')return a;if(c!=',')throw new IllegalArgumentException("comma");}}
for(String word:new String[]{"true","false","null"})if(s.startsWith(word,i)){i+=word.length();return word.equals("null")?null:Boolean.valueOf(word);}
int start=i;while(i<s.length()&&"-+0123456789.eE".indexOf(s.charAt(i))>=0)i++;String n=s.substring(start,i);if(n.indexOf('.')>=0||n.indexOf('e')>=0||n.indexOf('E')>=0)return Double.valueOf(n);return Long.valueOf(n);}
}
}
'''

GO=r'''
package main
import("encoding/json";"fmt";"math";"math/bits";"sort";"strings";"strconv";"container/heap";"container/list";"regexp";"time")
var _=math.Abs;var _=bits.OnesCount64;var _=sort.Ints;var _=strings.Compare;var _=strconv.Atoi;var _=heap.Init;var _=list.New;var _=regexp.MustCompile;var _=time.Now
func MciInt(v interface{})int64{return v.(int64)}
func MciArr(v interface{})[]interface{}{return v.([]interface{})}
func MciObj(v interface{})map[string]interface{}{return v.(map[string]interface{})}
'''


def quote(s):
    return json.dumps(s,ensure_ascii=False)


def c_quote(s):
    return '"'+''.join('\\'+c if c in ('"','\\') else f'\\{ord(c):03o}' if ord(c)<32 else c for c in s)+'"'


def rust_quote(s):
    return '"'+''.join('\\'+c if c in ('"','\\') else '\\n' if c=='\n' else '\\r' if c=='\r' else '\\t' if c=='\t' else f'\\u{{{ord(c):x}}}' if ord(c)<32 else c for c in s)+'"'


def literal(value,language):
    if language=='cpp':
        if value is None:return 'Mci(nullptr)'
        if type(value) is bool:return 'Mci('+str(value).lower()+')'
        if type(value) is int:return 'Mci('+str(value)+'LL)' if value!=-(2**63) else 'Mci((-9223372036854775807LL-1))'
        if type(value) is float:return 'Mci('+repr(value)+')'
        if type(value) is str:return 'Mci(string('+c_quote(value)+','+str(len(value.encode('utf8')))+'))'
        if type(value) is list:return 'Mci(Mci::Arr{'+','.join(literal(v,language) for v in value)+'})'
        return 'Mci(Mci::Obj{'+','.join('{'+c_quote(k)+','+literal(v,language)+'}' for k,v in value.items())+'})'
    if language=='rust':
        if value is None:return 'Mci::Null'
        if type(value) is bool:return 'Mci::Bool('+str(value).lower()+')'
        if type(value) is int:return 'Mci::Int('+str(value)+'i64)'
        if type(value) is float:return 'Mci::Float('+repr(value)+'f64)'
        if type(value) is str:return 'Mci::Str('+rust_quote(value)+'.into())'
        if type(value) is list:return 'Mci::Array(vec!['+','.join(literal(v,language) for v in value)+'])'
        return 'Mci::Object(BTreeMap::from(['+','.join('('+rust_quote(k)+'.into(),'+literal(v,language)+')' for k,v in value.items())+']))'
    if language=='java':
        if value is None:return 'null'
        if type(value) is bool:return str(value).lower()
        if type(value) is int:return str(value)+'L'
        if type(value) is float:return repr(value)+'d'
        if type(value) is str:return quote(value)
        if type(value) is list:return 'new ArrayList<Object>(Arrays.asList('+','.join(literal(v,language) for v in value)+'))'
        return 'Mci.map('+','.join(quote(k)+','+literal(v,language) for k,v in value.items())+')'
    if language=='golang':
        if value is None:return 'nil'
        if type(value) is bool:return str(value).lower()
        if type(value) is int:return 'int64('+str(value)+')'
        if type(value) is float:return 'float64('+repr(value)+')'
        if type(value) is str:return quote(value)
        if type(value) is list:return '[]interface{}{'+','.join(literal(v,language) for v in value)+'}'
        return 'map[string]interface{}{'+','.join(quote(k)+':'+literal(v,language) for k,v in value.items())+'}'
    raise ValueError('unsupported literal language')


def c_input(value,lines):
    name=f'_mci_v{len(lines)}'
    if type(value) is dict:
        lines.append(f'Mci*{name}=mci_object();')
        for k,v in value.items():
            child=c_input(v,lines);lines.append(f'mci_set({name},{c_quote(k)},{child});')
    elif type(value) is list:
        lines.append(f'Mci*{name}=mci_array();')
        for v in value:
            child=c_input(v,lines);lines.append(f'mci_push({name},{child});')
    else:
        expr=('mci_null()' if value is None else 'mci_boolean('+str(value).lower()+')' if type(value) is bool
              else 'mci_integer('+('(-9223372036854775807LL-1)' if value==-(2**63) else str(value)+'LL')+')' if type(value) is int
              else 'mci_number('+repr(value)+')' if type(value) is float else 'mci_string_n('+c_quote(value)+','+str(len(value.encode('utf8')))+')')
        lines.append(f'Mci*{name}={expr};')
    return name


def render(language,code,inputs,*,native_bridge=False):
    if not inputs:raise ValueError('empty input execution plan')
    if native_bridge:
        # Retarget only platform-owned calls. Never rewrite native solution or
        # bridge algorithms while changing the invocation name.
        marker='/*__MCIBENCH_NATIVE_SOURCE_INSERTION_84e31d__*/'
        extra=''
        if language=='java':
            imports=re.findall(r'(?m)^\s*import\s+[^;]+;',code)
            code=re.sub(r'(?m)^\s*import\s+[^;]+;','',code)
            code=re.sub(r'(?m)^public\s+(?=(?:final\s+)?class\s)','',code)
            extra='\n'.join(imports)+'\n'
        elif language=='csharp':
            from local.harness.render import clean_cs_user_code
            imports,code=clean_cs_user_code(code);extra='\n'.join(imports)+'\n'
        elif language=='golang':
            code=re.sub(r'(?m)^package\s+\w+\s*','',code)
            code=re.sub(r'(?ms)^import\s*\(.*?\)\s*','',code)
            code=re.sub(r'(?m)^import\s+[^\n]+\n','',code)
        platform=render(language,marker,inputs)
        if language in ('java','csharp'):platform=platform.replace('new Solution()','new MciAdapter()')
        else:platform=platform.replace('solve(','mci_adapter_solve(')
        return extra+platform.replace(marker,code)
    if language=='python3':
        from local.harness.render import PRELUDE
        return PRELUDE['python3']+'\nimport json as _mci_json\nfrom copy import deepcopy as _mci_copy\n'+code+f'\n_mci_inputs=_mci_json.loads({json.dumps(json.dumps(inputs,ensure_ascii=True))})\nfor _mci_i,_mci_a in enumerate(_mci_inputs):\n _mci_value=solve(_mci_copy(_mci_a))\n print("MCIBENCH_OUTPUT_V1 "+_mci_json.dumps({{"case":_mci_i,"op":0,"value":_mci_value}},allow_nan=False),flush=True)\n'
    if language=='javascript':
        strict='''
function _mci_json_value(value,seen=new Set()) {
 if(value===null||typeof value==='string'||typeof value==='boolean')return value;
 if(typeof value==='number'){if(!Number.isFinite(value))throw new Error('nonfinite JSON');return value;}
 if(typeof value!=='object'||seen.has(value))throw new Error('non JSON value or cycle');
 const proto=Object.getPrototypeOf(value);
 if(!Array.isArray(value)&&proto!==Object.prototype&&proto!==null)throw new Error('non JSON object');
 seen.add(value);let result;
 if(Array.isArray(value))result=Array.from(value,v=>_mci_json_value(v,seen));
 else {result=Object.create(null);for(const [k,v] of Object.entries(value))result[k]=_mci_json_value(v,seen);}
 seen.delete(value);return result;
}
'''
        return code+strict+'\n(async()=>{const inputs='+json.dumps(inputs,ensure_ascii=True)+';for(let i=0;i<inputs.length;i++){const value=_mci_json_value(await solve(structuredClone(inputs[i])));console.log("MCIBENCH_OUTPUT_V1 "+JSON.stringify({case:i,op:0,value}));}})().catch(e=>{console.error(e);process.exit(1)});\n'
    if language=='cpp':
        return CPP+'\n'+code+'\nint main(){\n'+''.join('{Mci data='+literal(a,language)+f';Mci out=solve(data);cout<<"MCIBENCH_OUTPUT_V1 {{\\\"case\\\":{i},\\\"op\\\":0,\\\"value\\\":";mci_emit(out);cout<<"}}"<<endl;}}\n' for i,a in enumerate(inputs))+'}\n'
    if language=='c':
        parts=[C,code,'\nint main(){\n']
        for i,a in enumerate(inputs):
            lines=[];root=c_input(a,lines)
            parts.append('{'+''.join(lines)+f'Mci*out=solve({root});printf("MCIBENCH_OUTPUT_V1 {{\\\"case\\\":{i},\\\"op\\\":0,\\\"value\\\":");mci_emit(out);puts("}}");fflush(stdout);}}\n')
        return ''.join(parts)+'return 0;}\n'
    if language=='rust':
        return RUST+'\n'+code+'\nfn main(){\n'+''.join('{let data='+literal(a,language)+f';let value=solve(data);println!("MCIBENCH_OUTPUT_V1 {{{{\\\"case\\\":{i},\\\"op\\\":0,\\\"value\\\":{{}}}}}}",mci_json(&value));}}\n' for i,a in enumerate(inputs))+'}\n'
    if language=='java':
        def input_json(a):
            text=json.dumps(a,ensure_ascii=True,separators=(',',':'))
            return 'String.join("",'+','.join(quote(text[n:n+8000]) for n in range(0,len(text),8000))+')'
        methods=''.join('static void case'+str(i)+'()throws Exception{Map<String,Object> data=Mci.obj(Mci.parse('+input_json(a)+f'));Object value=new Solution().solve(data);System.out.println("MCIBENCH_OUTPUT_V1 {{\\\"case\\\":{i},\\\"op\\\":0,\\\"value\\\":"+Mci.json(value)+"}}");}}\n' for i,a in enumerate(inputs))
        return JAVA+'\n'+code+'\npublic class Judge{'+methods+'public static void main(String[]args)throws Exception{'+''.join(f'case{i}();' for i in range(len(inputs)))+'}}\n'
    if language=='csharp':
        from local.harness.render import clean_cs_user_code
        imports,body=clean_cs_user_code(code)
        prefix='using System;using System.Collections.Generic;using System.Linq;using System.Text;using System.Text.Json;using System.Numerics;using System.Globalization;\n'
        return prefix+'\n'.join(imports)+'\n'+body+'\npublic class Judge{public static void Main(string[]args){\n'+''.join('{using var doc=JsonDocument.Parse('+quote(json.dumps(a,ensure_ascii=True))+f');var value=new Solution().Solve(doc.RootElement);Console.WriteLine("MCIBENCH_OUTPUT_V1 "+JsonSerializer.Serialize(new{{@case={i},op=0,value=value}}));}}\n' for i,a in enumerate(inputs))+'}}\n'
    if language=='golang':
        return GO+'\n'+code+'\nfunc main(){\n'+''.join('{data:='+literal(a,language)+f';value:=solve(data);b,err:=json.Marshal(map[string]interface{{}}{{"case":{i},"op":0,"value":value}});if err!=nil{{panic(err)}};fmt.Println("MCIBENCH_OUTPUT_V1 "+string(b))}}\n' for i,a in enumerate(inputs))+'}\n'
    raise ValueError('unknown portable function language')
