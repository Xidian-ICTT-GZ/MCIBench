"""Reviewed manual native references, separate from every generated candidate.

These sources are not model samples or functional mutation-rate fixtures.
"""
from local.lab import source_guard
source_guard.register(__file__)

SOURCES={
 2618:'var checkIfInstanceOf=(obj,cls)=>obj!=null&&typeof cls==="function"&&Object(obj) instanceof cls;',
 2620:'var createCounter=n=>()=>n++;',
 2626:'var reduce=(nums,fn,init)=>{for(const n of nums)init=fn(init,n);return init;};',
 2629:'var compose=fs=>x=>{for(let i=fs.length-1;i>=0;i--)x=fs[i](x);return x;};',
 2630:'''var memoize=fn=>{const root=new Map(),result=Symbol('result');return (...args)=>{
  let node=root;for(const arg of args){if(!node.has(arg))node.set(arg,new Map());node=node.get(arg);}
  if(!node.has(result))node.set(result,fn(...args));return node.get(result);};};''',
 2631:'Array.prototype.groupBy=function(fn){const out=Object.create(null);for(const item of this){const key=fn(item);(out[key]??=[]).push(item);}return out;};',
 2634:'var filter=(arr,fn)=>{const out=[];for(let i=0;i<arr.length;i++)if(fn(arr[i],i))out.push(arr[i]);return out;};',
 2635:'var map=(arr,fn)=>{const out=[];for(let i=0;i<arr.length;i++)out.push(fn(arr[i],i));return out;};',
 2666:'var once=fn=>{let used=false;return (...args)=>{if(used)return undefined;used=true;return fn(...args);};};',
 2693:'Function.prototype.callPolyfill=function(context,...args){return Reflect.apply(this,context,args);};',
 2704:'var expect=val=>({toBe(other){if(val!==other)throw new Error("Not Equal");return true;},notToBe(other){if(val===other)throw new Error("Equal");return true;}});',
 2724:'var sortBy=(arr,fn)=>arr.slice().sort((a,b)=>fn(a)-fn(b));',
 2622:'''var TimeLimitedCache=function(){this.items=new Map();};
TimeLimitedCache.prototype.set=function(k,v,d){const exists=this.get(k)!==-1;this.items.set(k,{value:v,expires:Date.now()+d});return exists;};
TimeLimitedCache.prototype.get=function(k){const row=this.items.get(k);return row&&row.expires>Date.now()?row.value:-1;};
TimeLimitedCache.prototype.count=function(){return [...this.items.keys()].filter(k=>this.get(k)!==-1).length;};''',
 2627:'var debounce=(fn,t)=>{let timer;return (...args)=>{clearTimeout(timer);timer=setTimeout(()=>fn(...args),t);};};',
 2637:'var timeLimit=(fn,t)=>(...args)=>Promise.race([fn(...args),new Promise((_,reject)=>setTimeout(()=>reject("Time Limit Exceeded"),t))]);',
 2715:'var cancellable=(fn,args,t)=>{const id=setTimeout(()=>fn(...args),t);return ()=>clearTimeout(id);};',
 2721:'''var promiseAll=functions=>new Promise((resolve,reject)=>{const out=new Array(functions.length);let remaining=functions.length;
 functions.forEach((fn,i)=>Promise.resolve(fn()).then(value=>{out[i]=value;if(--remaining===0)resolve(out);},reject));});''',
 2723:'var addTwoPromises=async(a,b)=>(await a)+(await b);',
 2725:'var cancellable=(fn,args,t)=>{fn(...args);const id=setInterval(()=>fn(...args),t);return ()=>clearInterval(id);};',
 2650:'''var cancellable=generator=>{let ended=false,resolve,reject;
 const promise=new Promise((a,b)=>{resolve=a;reject=b;});
 function advance(method,value){if(ended)return;let step;try{step=generator[method](value);}catch(e){ended=true;reject(e);return;}
  if(step.done){ended=true;resolve(step.value);return;}
  Promise.resolve(step.value).then(v=>advance('next',v),e=>advance('throw',e));}
 advance('next');return [()=>{if(ended)return;ended=true;try{const step=generator.throw('Cancelled');resolve(step.value);}catch(e){reject(e);}},promise];};''',
}
