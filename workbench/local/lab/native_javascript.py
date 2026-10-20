"""Trusted invocation/observation adapters; never solve the target algorithm."""
import json

from local.lab import javascript_protocol as protocol,javascript_async as asynchronous,javascript_clock as clock,source_guard
source_guard.register(__file__)

PREFIX = r'''
function _mci_callback(spec) {
 function expression(e,args,context) {
  if(Object.hasOwn(e,'literal'))return e.literal;
  if(Object.hasOwn(e,'arg'))return args[e.arg];
  if(Object.hasOwn(e,'context'))return context[e.context];
  const a=e.args.map(x=>expression(x,args,context));
  switch(e.op){
   case 'add':return a[0]+a[1];case 'subtract':return a[0]-a[1];
   case 'multiply':return a[0]*a[1];case 'modulo':return a[0]%a[1];case 'power':return a[0]**a[1];
   case 'negate':return -a[0];case 'get':return a[0][a[1]];
   case 'string':return String(a[0]);case 'gt':return a[0]>a[1];
   case 'lt':return a[0]<a[1];case 'ge':return a[0]>=a[1];case 'le':return a[0]<=a[1];
   case 'strict_equal':return a[0]===a[1];case 'strict_not_equal':return a[0]!==a[1];
   default:throw new Error('unsupported callback protocol');
  }
 }
 return function(...args) {
  if(spec.kind==='merge_objects')return {...args[0],...args[1]};
  if(spec.kind==='tax_message')return `The cost of the ${this.item} is ${args[0]*args[1]}`;
  if(spec.kind==='expression')return expression(spec.expr,args,this);
  throw new Error('unsupported callback kind');
 };
}
function _mci_references(data) {
 const pool=data.objects;
 function restore(v) {
  if(v===null||typeof v!=='object')return v;
  if(!Array.isArray(v)&&Object.keys(v).length===1&&Object.hasOwn(v,'$ref')) {
   if(!Object.hasOwn(pool,v.$ref))throw new Error('missing reference');
   return pool[v.$ref];
  }
  if(Array.isArray(v))return v.map(restore);
  const out={};for(const k of Object.keys(v))Object.defineProperty(out,k,{value:restore(v[k]),enumerable:true,writable:true,configurable:true});return out;
 }
 return restore;
}
function _mci_instance_input(data) {
 const types={Date,Number,String,Boolean,Object,Array,Function,undefined:undefined,null:null};
 function type(name) {
  if(Object.hasOwn(types,name))return types[name];
  const parent=data.classes[name];
  const result=parent===null?class {}:class extends type(parent) {};
  Object.defineProperty(types,name,{value:result,enumerable:true});return result;
 }
 let obj;
 if(Object.hasOwn(data.object,'instance'))obj=new (type(data.object.instance))();
 else if(Object.hasOwn(data.object,'class'))obj=type(data.object.class);
 else if(Object.hasOwn(data.object,'primitive'))obj=data.object.primitive;
 else obj=undefined;
 return [obj,type(data.class)];
}
'''

SUFFIXES = {
 2618: 'return checkIfInstanceOf(..._mci_instance_input(data));',
 2620: 'const counter=createCounter(data.n);return data.calls.map(()=>counter());',
 2626: 'return reduce(data.nums,_mci_callback(data.fn),data.init);',
 2629: 'return compose(data.functions.map(_mci_callback))(data.x);',
 2634: 'return filter(data.arr,_mci_callback(data.fn));',
 2635: 'return map(data.arr,_mci_callback(data.fn));',
 2631: 'return data.array.groupBy(_mci_callback(data.fn));',
 2724: 'return sortBy(data.arr,_mci_callback(data.fn));',
 2693: 'const fn=_mci_callback(data.fn);return fn.callPolyfill(...data.args);',
 2704: '''const restore=_mci_references(data);try {
  return {value:expect(restore(data.value))[data.method](restore(data.other))};
 } catch(e) { return {error:e instanceof Error?e.message:String(e)}; }''',
 2630: '''let calls=0;const fn=_mci_callback(data.fn);const restore=_mci_references(data);
 const cached=memoize(function(...args){calls++;return fn(...args);});
 return data.inputs.map(args=>({val:cached(...restore(args)),calls}));''',
 2666: '''let calls=0;const fn=_mci_callback(data.fn);
 const wrapped=once(function(...args){calls++;return fn(...args);});const results=[];
 for(const args of data.calls){const before=calls;const value=wrapped(...args);
  if(value!==undefined||calls!==before)results.push({calls,value:value===undefined?{$undefined:true}:value});}
 return results;''',
}

ENTRIES={2618:'checkIfInstanceOf',2620:'createCounter',2626:'reduce',2629:'compose',2630:'memoize',
         2631:'Array.prototype.groupBy',2634:'filter',2635:'map',2666:'once',2693:'Function.prototype.callPolyfill',2704:'expect',2724:'sortBy'}
ENTRIES.update({2622:'TimeLimitedCache',2627:'debounce',2637:'timeLimit',2650:'cancellable',2715:'cancellable',2721:'promiseAll',2723:'addTwoPromises',2725:'cancellable'})


def bridge(qid,descriptor):
    if qid in asynchronous.QIDS:
        if not all(asynchronous.valid(qid,c['args']) for c in descriptor['official']):return None
        return {'prefix':PREFIX+clock.SOURCE,'suffix':clock.suffix(qid)}
    if qid not in protocol.QIDS:return None
    if not all(protocol.valid(qid,c['args']) for c in descriptor['official']):return None
    return {'prefix':PREFIX,'suffix':'\nfunction mci_adapter_solve(data) {\n'+SUFFIXES[qid]+'\n}\n'}


def negative_source(qid,marker):
    if qid not in ENTRIES:return None
    entry=ENTRIES[qid]
    return ('' if '.' in entry else 'var ')+entry+'=function(){throw new Error('+json.dumps(marker)+');};'


def sensitivity_source(qid):
    """Gate fixtures only; these are NOT functional mutation-rate samples."""
    bodies={2618:'return false;',2620:'return ()=>0;',2626:'return 0;',2629:'return ()=>0;',
        2630:'return arguments[0];',2631:'return {};',2634:'return [];',2635:'return [];',
        2666:'return arguments[0];',2693:'return null;',2704:'return {toBe:()=>false,notToBe:()=>false};',2724:'return [];',
        2622:'',2627:'return ()=>{};',2637:'return async()=>0;',2650:'return [()=>{},Promise.resolve(0)];',
        2715:'return ()=>{};',2721:'return Promise.resolve([]);',2723:'return Promise.resolve(0);',2725:'return ()=>{};'}
    if qid not in bodies:return None
    entry=ENTRIES[qid]
    if qid==2622:return 'var TimeLimitedCache=function(){};TimeLimitedCache.prototype.set=()=>false;TimeLimitedCache.prototype.get=()=>-1;TimeLimitedCache.prototype.count=()=>0;'
    return ('' if '.' in entry else 'var ')+entry+'=function(){'+bodies[qid]+'};'


def observed_entry(result,marker):
    """API tasks may correctly serialize a thrown error instead of crashing."""
    if result['ac_status']=='Runtime Error' and marker in result['_meta']['error']:return True
    return (result['ac_status']=='Collected' and bool(result.get('outputs')) and
            all(marker in json.dumps(value,ensure_ascii=False) for value in result['outputs']))
