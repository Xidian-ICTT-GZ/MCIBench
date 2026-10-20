"""Deterministic Node timer controller with native Promise microtask checkpoints."""
from local.lab import source_guard
source_guard.register(__file__)

SOURCE = r'''
const _mci_real_immediate=globalThis.setImmediate;
const _mci_real_Date=globalThis.Date;
let _mci_clock=null;
class _MciClock {
 constructor(){this.now=0;this.serial=0;this.timers=new Map();this.steps=0;}
 schedule(fn,delay,args,interval=false){
  if(typeof fn!=='function')throw new TypeError('timer callback must be a function');
  delay=Number(delay)||0;if(!Number.isFinite(delay)||delay<0)delay=0;
  if(interval&&delay===0)delay=1;
  const id=++this.serial;const timer={id,seq:id,at:this.now+delay,delay,fn,args,interval};
  this.timers.set(id,timer);
  return {id,ref(){return this},unref(){return this},hasRef(){return true},[Symbol.toPrimitive](){return id}};
 }
 clear(id){this.timers.delete(Number(id));}
 next(){let found=null;for(const t of this.timers.values())if(!found||t.at<found.at||t.at===found.at&&t.seq<found.seq)found=t;return found;}
 async checkpoint(){await new Promise(resolve=>_mci_real_immediate(resolve));}
 async fire(timer){
  if(++this.steps>10000)throw new Error('deterministic timer event budget exceeded');
  this.now=timer.at;
  if(!timer.interval)this.timers.delete(timer.id);
  else {timer.at+=timer.delay;timer.seq=++this.serial;}
  timer.fn(...timer.args);await this.checkpoint();
 }
 async until(end){
  await this.checkpoint();let timer;
  while((timer=this.next())&&timer.at<=end)await this.fire(timer);
  this.now=end;await this.checkpoint();
 }
 async settle(promise,timed=false,timeKey='time'){
  let finished=false;let output;
  Promise.resolve(promise).then(value=>{output={resolved:value};if(timed)output[timeKey]=this.now;finished=true;},
   error=>{output={rejected:error instanceof Error?error.message:error};if(timed)output[timeKey]=this.now;finished=true;});
  await this.checkpoint();
  while(!finished){const next=this.next();if(!next)throw new Error('candidate promise did not settle and has no pending timer');await this.fire(next);}
  return output;
 }
}
globalThis.setTimeout=(fn,delay,...args)=>{if(!_mci_clock)throw new Error('timer outside frozen case');return _mci_clock.schedule(fn,delay,args);};
globalThis.setInterval=(fn,delay,...args)=>{if(!_mci_clock)throw new Error('timer outside frozen case');return _mci_clock.schedule(fn,delay,args,true);};
globalThis.clearTimeout=globalThis.clearInterval=id=>{if(_mci_clock)_mci_clock.clear(id);};
function _MciDate(...args){
 const now=_mci_clock?_mci_clock.now:0;
 if(!new.target)return new _mci_real_Date(now).toString();
 return Reflect.construct(_mci_real_Date,args.length?args:[now],new.target);
}
Object.setPrototypeOf(_MciDate,_mci_real_Date);_MciDate.prototype=_mci_real_Date.prototype;
_MciDate.now=()=>_mci_clock?_mci_clock.now:0;globalThis.Date=_MciDate;
Object.defineProperty(globalThis,'performance',{value:{now:()=>_mci_clock?_mci_clock.now:0},configurable:true});
function _mci_promise(spec){
 return new Promise((resolve,reject)=>{
  const settle=()=>{(spec.outcome==='reject'?reject:resolve)(Object.hasOwn(spec,'value')?spec.value:undefined);};
  if(spec.delay===null)settle();else setTimeout(settle,spec.delay);
 });
}
function* _mci_generator(program){
 const locals=Object.create(null);
 function expr(e){
  if(Object.hasOwn(e,'literal'))return e.literal;
  if(Object.hasOwn(e,'local'))return locals[e.local];
  return expr(e.args[0])+expr(e.args[1]);
 }
 function* run(steps){
  for(const s of steps){
   if(s.op==='return')return {returned:true,value:expr(s.value)};
   if(s.op==='throw')throw expr(s.value);
   if(s.op==='set')locals[s.target]=expr(s.value);
   if(s.op==='yield'){
    const value=yield _mci_promise(s.promise);
    if(Object.hasOwn(s,'target'))locals[s.target]=s.mode==='add'?locals[s.target]+value:value;
   }
   if(s.op==='try'){
    let completion;
    try{completion=yield* run(s.body);}catch(e){locals[s.error]=e;completion=yield* run(s.catch);}
    if(completion&&completion.returned)return completion;
   }
  }
  return {returned:false};
 }
 const completion=yield* run(program);return completion.value;
}
'''

SUFFIXES={
 2622: '''const cache=new TimeLimitedCache();const result=new Array(data.actions.length);result[0]=null;
  const events=data.actions.map((action,i)=>({action,i,t:data.timeDelays[i]})).slice(1).sort((a,b)=>a.t-b.t||a.i-b.i);
  for(const event of events){await clock.until(event.t);result[event.i]=cache[event.action](...data.values[event.i]);}
  return result;''',
 2627: '''const outputs=[];const fn=debounce((...inputs)=>outputs.push({t:clock.now,inputs}),data.t);
  for(const c of data.calls)setTimeout(()=>fn(...c.inputs),c.t);
  await clock.until(Math.max(...data.calls.map(c=>c.t))+data.t+1);return outputs;''',
 2637: '''const fn=async(...args)=>{if(data.fn.delay!==null)await new Promise(res=>setTimeout(res,data.fn.delay));
   const value=_mci_callback({kind:'expression',expr:data.fn.expr})(...args);
   if(data.fn.outcome==='reject')throw value;return value;};
  return await clock.settle(timeLimit(fn,data.t)(...data.inputs),true);''',
 2650: '''const pair=cancellable(_mci_generator(data.program));
  if(!Array.isArray(pair)||pair.length!==2||typeof pair[0]!=='function'||!pair[1]||typeof pair[1].then!=='function')throw new Error('invalid cancellable return contract');
  if(data.cancelledAt!==null)setTimeout(pair[0],data.cancelledAt);
  return await clock.settle(pair[1]);''',
 2715: '''const outputs=[];const fn=_mci_callback(data.fn);
  const cancel=cancellable((...args)=>outputs.push({time:clock.now,returned:fn(...args)}),data.args,data.t);
  if(typeof cancel!=='function')throw new Error('cancel callback missing');
  setTimeout(cancel,data.cancelTimeMs);await clock.until(Math.max(data.t,data.cancelTimeMs)+1);return outputs;''',
 2725: '''const outputs=[];const fn=_mci_callback(data.fn);
  const cancel=cancellable((...args)=>outputs.push({time:clock.now,returned:fn(...args)}),data.args,data.t);
  if(typeof cancel!=='function')throw new Error('cancel callback missing');
  setTimeout(cancel,data.cancelTimeMs);await clock.until(data.cancelTimeMs+data.t+1);return outputs;''',
 2721: '''return await clock.settle(promiseAll(data.functions.map(spec=>()=>_mci_promise(spec))),true,'t');''',
 2723: '''const result=await clock.settle(addTwoPromises(_mci_promise(data.promise1),_mci_promise(data.promise2)));
  if(Object.hasOwn(result,'rejected'))throw result.rejected;return result.resolved;''',
}


def suffix(qid):
    return '\nasync function mci_adapter_solve(data){\nconst clock=new _MciClock();_mci_clock=clock;\ntry{\n'+SUFFIXES[qid]+'\n}finally{clock.timers.clear();_mci_clock=null;}\n}\n'
