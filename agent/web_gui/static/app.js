/* ClaudeZ Web v2.1 — Global UI + Full Config Panel */
(function(){
var S={
  busy:0,last:'',ab:1,sse:null,toolCount:0,toolNames:{},
  events:[],evFilter:'all',_sending:0,config:{}
};

function ts(){return new Date().toLocaleTimeString()}
function div(c){var d=document.createElement('div');d.className=c;return d}
function $(id){return document.getElementById(id)}
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML}
function scrollB(){msgs.scrollTop=msgs.scrollHeight}
function qs(s){return document.querySelector(s)}

var msgs=$('msgs'),ib=$('inp'),sb=$('send-btn'),st=$('st-t'),hds=$('hd-s'),toasts=$('toasts'),scrollH=$('scroll-hint');

/* ═══════════════════════════════════════════
   PARTICLE BACKGROUND
   ═══════════════════════════════════════════ */
(function(){
var cv=$('bg-canvas'),ctx=cv.getContext('2d'),W,H,parts=[],mx=0,my=0,ma=0,CS=['0,212,255','124,58,237','244,114,182','52,211,153'];
function resize(){W=cv.width=window.innerWidth;H=cv.height=window.innerHeight}
resize();window.addEventListener('resize',resize);
for(var i=0;i<100;i++)parts.push({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-0.5)*.4,vy:(Math.random()-0.5)*.4,r:Math.random()*1.8+.3,o:Math.random()*.35+.08,c:CS[Math.floor(Math.random()*4)],ps:Math.random()*.02+.005,po:Math.random()*Math.PI*2});
document.addEventListener('mousemove',function(e){mx=e.clientX;my=e.clientY;ma=1});
document.addEventListener('mouseleave',function(){ma=0});
function anim(t){
  ctx.clearRect(0,0,W,H);
  parts.forEach(function(p){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;var d=ma?Math.hypot(p.x-mx,p.y-my):999,sc=d<150?1+(1-d/150)*1.2:1,ro=p.o*(.7+.3*Math.sin(t*p.ps+p.po));if(d<80)ro=Math.min(1,ro+.3);ctx.beginPath();ctx.arc(p.x,p.y,p.r*sc,0,Math.PI*2);ctx.fillStyle='rgba('+p.c+','+ro+')';ctx.fill()});
  for(var i=0;i<parts.length;i++)for(var j=i+1;j<parts.length;j++){var dx=parts[i].x-parts[j].x,dy=parts[i].y-parts[j].y,dist=Math.hypot(dx,dy);if(dist<100){ctx.beginPath();ctx.moveTo(parts[i].x,parts[i].y);ctx.lineTo(parts[j].x,parts[j].y);ctx.strokeStyle='rgba(124,58,227,'+(1-dist/100)*.08+')';ctx.lineWidth=.4;ctx.stroke()}}
  if(ma)for(var i=0;i<parts.length;i++){var dx=parts[i].x-mx,dy=parts[i].y-my,dist=Math.hypot(dx,dy);if(dist<160){ctx.beginPath();ctx.moveTo(parts[i].x,parts[i].y);ctx.lineTo(mx,my);ctx.strokeStyle='rgba(0,212,255,'+(1-dist/160)*.15+')';ctx.lineWidth=.5;ctx.stroke()}}
  requestAnimationFrame(anim)
}
anim(0)
})();

/* ═══════════════════════════════════════════
   MARKDOWN RENDERER
   ═══════════════════════════════════════════ */
function md(t){
  if(!t)return'';
  var h=t,cbs=[],ics=[];
  h=h.replace(/```(\w*)\n?([\s\S]*?)```/g,function(m,l,c){var i=cbs.length;cbs.push('<pre><code>'+esc(c)+'</code></pre>');return'%%CB'+i+'%%'});
  h=h.replace(/`([^`]+)`/g,function(m,c){var i=ics.length;ics.push('<code>'+esc(c)+'</code>');return'%%IC'+i+'%%'});
  h=h.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
  h=h.replace(/^# (.+)$/gm,'<b style="font-size:15px;color:var(--accent)">$1</b>');
  h=h.replace(/^## (.+)$/gm,'<b style="font-size:13px">$1</b>');
  h=h.replace(/%%CB(\d+)%%/g,function(m,i){return cbs[parseInt(i)]||''});
  h=h.replace(/%%IC(\d+)%%/g,function(m,i){return ics[parseInt(i)]||''});
  h=h.replace(/\n/g,'<br>');
  return h;
}

var I={read:'📖',write:'✏️',edit:'🔧',glob:'🔎',grep:'🔎',bash:'💻',web:'🌐',web_search:'🔍',process:'⚙️',monitor:'📊',subagent:'🧠',artifact:'📦',workflow:'📋',webhook:'🔌',plan:'📋',task:'✅'};
function hasDiff(t){return t.indexOf('@@ -')>=0||(t.indexOf('\n+')>=0&&t.indexOf('\n-')>=0)||t.indexOf('+++')>=0}
var LM={py:'python',js:'javascript',ts:'typescript',jsx:'javascript',tsx:'typescript',html:'html',css:'css',json:'json',md:'markdown',yaml:'yaml',yml:'yaml',rs:'rust',go:'go',java:'java',cpp:'cpp',c:'c',sh:'bash',bash:'bash',sql:'sql',xml:'xml',php:'php',rb:'ruby',swift:'swift',kt:'kotlin'};
function hl(line,lang){
  var h=esc(line),kws=['function ','def ','class ','return ','if ','else ','elif ','for ','while ','import ','from ','export ','const ','let ','var ','async ','await ','try ','catch ','throw ','new ','this ','null ','undefined ','true ','false ','None ','True ','False ','self ','public ','private ','static ','interface ','enum ','type ','package ','struct ','impl ','trait ','fn ','mut ','pub ','in ','not ','and ','or ','is ','lambda ','yield ','with ','as ','except ','finally ','raise ','pass ','break ','continue ','switch ','case ','default '];
  kws.forEach(function(kw){var re=new RegExp('(^|\\W)('+kw.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')(?=\\W|$)','g');h=h.replace(re,'$1<span style=\"color:#7c3aed;font-weight:600\">$2</span>')});
  h=h.replace(/(&lt;!--[\s\S]*?--&gt;|#.+$|\/\/.+$)/gm,'<span style="color:#555580;font-style:italic">$1</span>');
  h=h.replace(/("(?:[^"\\]|\\.)*")/g,'<span style="color:#ce9178">$1</span>');
  h=h.replace(/('(?:[^'\\]|\\.)*')/g,'<span style="color:#ce9178">$1</span>');
  return h;
}

function renderDiff(refEl,diffText,filePath){
  var lines=diffText.split('\n'),db=div('diff-block'),lang='';
  if(filePath){var ext=filePath.split('.').pop().toLowerCase();lang=LM[ext]||''}
  var add=0,del=0;lines.forEach(function(l){if(l.startsWith('+')&&!l.startsWith('+++'))add++;if(l.startsWith('-')&&!l.startsWith('---'))del++});
  var pm=(add?'+'+add:'')+(del?'  -'+del:'');
  var hdr=div('diff-hdr');hdr.innerHTML='<span>📝 '+pm+(lang?'  .'+lang:'')+'</span><span style="margin-left:auto;font-size:10px;color:var(--fg-3)">[收起]</span>';
  hdr.onclick=function(){db.classList.toggle('closed');hdr.querySelector('span:last-child').textContent=db.classList.contains('closed')?'[展开]':'[收起]'};
  var body=div('diff-body'),lineNum=0;
  lines.forEach(function(l){
    if(l.startsWith('@@')){var h=div('diff-hunk');h.textContent=l;body.appendChild(h);var m=l.match(/@@\s+-\d+(?:,\d+)?\s+\+(\d+)/);if(m)lineNum=parseInt(m[1])-1;return}
    if(l.startsWith('---')||l.startsWith('+++')||l.startsWith('\\ '))return;
    var dl=div('diff-line');
    if(l.startsWith('+')){dl.className+=' diff-add';dl.innerHTML='<span class="diff-num"></span><span class="diff-sig">+</span><span class="diff-code">'+hl(l.substring(1),lang)+'</span>'}
    else if(l.startsWith('-')){dl.className+=' diff-del';dl.innerHTML='<span class="diff-num"></span><span class="diff-sig">-</span><span class="diff-code">'+hl(l.substring(1),lang)+'</span>'}
    else{var ctx=l.startsWith(' ')?l.substring(1):l;dl.className+=' diff-ctx';lineNum++;dl.innerHTML='<span class="diff-num">'+lineNum+'</span><span class="diff-sig"> </span><span class="diff-code">'+esc(ctx)+'</span>'}
    body.appendChild(dl)
  });
  db.appendChild(hdr);db.appendChild(body);
  refEl.parentNode.insertBefore(db,refEl.nextSibling);scrollB();
  var total=body.querySelectorAll('.diff-line').length;
  if(total>30){db.classList.add('closed');hdr.querySelector('span:last-child').textContent='[展开]'}
  if(total>50){body.style.maxHeight='260px';body.style.overflowY='auto'}
}

/* ═══════════════════════════════════════════
   MESSAGE RENDERERS
   ═══════════════════════════════════════════ */
function addText(delta){
  var last=msgs.lastElementChild;
  if(last&&last.classList.contains('msg-asst')){
    last._acc=(last._acc||'')+delta;
    var mc=last.querySelector('.mc');
    if(mc)mc.innerHTML=md(last._acc)
  }else{
    var el=div('msg msg-asst');
    el.innerHTML='<div class="mc">'+md(delta)+'</div><div class="mt">'+ts()+'</div>';
    el._acc=delta;msgs.appendChild(el)
  }
  scrollB()
}
function addUser(text){
  var el=div('msg msg-user');
  el.innerHTML='<div class="mc">'+esc(text)+'</div><div class="mt">'+ts()+'</div>';
  msgs.appendChild(el);scrollB()
}
function addToolCall(name,path,extra){
  var icon=I[name]||'[?]';
  var eh=extra?' <span class="tl-extra">'+esc(extra)+'</span>':'';
  var ph=path?'<span class="tl-target">'+esc(path)+'</span>':'';
  var el=div('tool-line');
  el.dataset.tname=name;
  el.innerHTML='<span class="tl-icon">'+icon+'</span><span class="tl-name">'+name+'</span>'+ph+eh+'<span class="tl-status">…</span>';
  msgs.appendChild(el);scrollB();
  updateTD(name,'running');
  return el;
}
function addToolResult(name,isErr,durMs,resultText,toolPath){
  var tools=msgs.querySelectorAll('.tool-line'),tc=null;
  for(var i=0;i<tools.length;i++){if(tools[i].dataset.tname===name){var st=tools[i].querySelector('.tl-status');if(st&&st.textContent==='…'){tc=tools[i];break}}}
  if(!tc)for(var i=0;i<tools.length;i++){var st=tools[i].querySelector('.tl-status');if(st&&st.textContent==='…'){tc=tools[i];break}}
  if(!tc)return;
  var st=tc.querySelector('.tl-status'),ds=durMs?' <span class="tl-time">'+(durMs/1000).toFixed(1)+'s</span>':'';
  if(isErr){st.innerHTML='[✗]'+ds;st.className='tl-status tl-err';updateTD(name,'error')}
  else{st.innerHTML='[✓]'+ds;st.className='tl-status tl-done';updateTD(name,'done')}
  S.toolCount++;$('st-c').textContent=S.toolCount;
  if(resultText&&hasDiff(resultText))renderDiff(tc,resultText,toolPath||'')
}
function addToolOutput(name,line){
  var tools=msgs.querySelectorAll('.tool-line'),el=null;
  for(var i=tools.length-1;i>=0;i--){if(tools[i].dataset.tname===name){el=tools[i];break}}
  if(!el){addToolCall(name,'','');el=msgs.lastElementChild}
  // Check if output container already exists
  var con=el.nextElementSibling;
  if(!con||!con.classList.contains('tl-output-con')){
    con=div('tl-output-con');
    var out=div('tl-output');
    con.appendChild(out);
    el.parentNode.insertBefore(con,el.nextSibling)
  }
  var out=con.querySelector('.tl-output');
  if(out)out.textContent+=line+'\n';
  scrollB()
}
function addThink(text){
  var last=msgs.lastElementChild;
  if(last&&last.classList.contains('think-block')){var b=last.querySelector('.think-b');if(b){b.textContent+=text;scrollB();return last}}
  var el=div('think-block');el.innerHTML='<div class="think-h">🧠 思考</div><div class="think-b">'+esc(text)+'</div>';msgs.appendChild(el);
  el.querySelector('.think-h').onclick=function(){el.classList.toggle('collapsed')};scrollB();return el
}
function addSys(text){var el=div('msg msg-sys');el.innerHTML='<div class="mc">'+esc(text)+'</div>';msgs.appendChild(el);scrollB()}
function addErr(text){var el=div('msg msg-err');el.innerHTML='<div class="mc">'+esc(text)+'</div>';msgs.appendChild(el);scrollB()}

/* ═══════════════════════════════════════════
   SSE CONNECTION
   ═══════════════════════════════════════════ */
function connectSSE(){
  if(S.sse)S.sse.close();
  S.sse=new EventSource('/api/stream');
  S.sse.addEventListener('text_delta',function(e){try{var d=JSON.parse(e.data);if(d.delta)addText(d.delta)}catch(x){}});
  S.sse.addEventListener('thinking_delta',function(e){try{var d=JSON.parse(e.data);if(d.delta)addThink(d.delta)}catch(x){}});
  S.sse.addEventListener('tool_use_start',function(e){try{var d=JSON.parse(e.data);addToolCall(d.tool_name,d.file_path||'',d.args_preview||'');addEvent('tool','> '+d.tool_name+(d.file_path?' '+d.file_path:''));setBusy(1)}catch(x){}});
  S.sse.addEventListener('tool_result',function(e){try{var d=JSON.parse(e.data);addToolResult(d.tool_name,d.status==='error',d.duration_ms||0,d.result||'',d.file_path||'');addEvent('tool',(d.status==='error'?'✗ ':'✓ ')+d.tool_name+(d.duration_ms?' '+(d.duration_ms/1000).toFixed(1)+'s':''))}catch(x){}});
  S.sse.addEventListener('tool_output',function(e){try{var d=JSON.parse(e.data);if(d.line)addToolOutput(d.tool_name,d.line)}catch(x){}});
  S.sse.addEventListener('session_start',function(e){try{setBusy(1);addEvent('session','▶ 开始')}catch(x){}});
  S.sse.addEventListener('session_end',function(e){try{setBusy(0);addEvent('session','■ 结束');C.updateDebugSummary()}catch(x){}});
  S.sse.addEventListener('plugins_changed',function(e){try{addEvent('session','插件状态已变更');buildPlugins();buildTools()}catch(x){}});
  S.sse.addEventListener('error',function(e){try{var d=JSON.parse(e.data);if(d.message){addErr(d.message);setBusy(0);addEvent('error',d.message)}}catch(x){}})
}

/* ═══════════════════════════════════════════
   CORE ACTIONS
   ═══════════════════════════════════════════ */
function send(){
  if(S._sending)return;
  var t=ib.value.trim();if(!t||S.busy)return;
  S.last=t;ib.value='';ib.style.height='auto';
  S._sending=true;setBusy(1);addUser(t);
  fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})})
  .then(function(r){return r.json()})
  .then(function(d){if(d.status!=='ok'){addErr(d.message||'发送失败');setBusy(0)}S._sending=false})
  .catch(function(e){addErr('网络错误: '+e.message);setBusy(0);S._sending=false})
}
function stop(){if(!S.busy)return;fetch('/api/stop',{method:'POST'}).catch(function(){});setBusy(0);addSys('已终止')}
function clear(){
  msgs.innerHTML='';S.toolCount=0;S.events=[];
  $('st-c').textContent='0';
  $('ev-c').innerHTML='<div style="padding:20px;text-align:center;color:var(--fg-3);font-size:11px">等待事件…</div>';
  fetch('/api/clear',{method:'POST'}).catch(function(){});
  addSys('已清空');toast('已清空','info')
}
function setBusy(b){
  S.busy=b;sb.disabled=b;sb.textContent=b?'…':'发送';ib.disabled=b;
  $('btn-stop').disabled=!b;
  hds.className='hd-status'+(b?' busy':'');
  st.textContent=b?'工作中':'就绪';
}

/* ═══════════════════════════════════════════
   EVENTS PANEL
   ═══════════════════════════════════════════ */
var EV_TYPES=['all','session','tool','thought','text','error'];var EV_LABELS={all:'全部',session:'会话',tool:'工具',thought:'思考',text:'文本',error:'错误'};var EV_SHORT={session:'会话',tool:'工具',thought:'思考',text:'文本',error:'错误'};
function renderEvBar(){
  var c=$('ev-bar');c.innerHTML='<span class="ev-count" id="ev-count">0</span>';
  EV_TYPES.forEach(function(t){
    var b=document.createElement('button');
    b.className='ev-f'+(t==='all'?' act':'');
    b.textContent=EV_LABELS[t]||t;
    b.onclick=function(){c.querySelectorAll('.ev-f').forEach(function(x){x.classList.remove('act')});b.classList.add('act');S.evFilter=t;renderEvLog()};
    c.appendChild(b)
  })
}
function addEvent(type,data){
  S.events.push({type:type,data:data||'',ts:Date.now()});
  if(S.events.length>500)S.events.shift();
  var c=$('ev-count');if(c)c.textContent=S.events.length;
  renderEvLog()
}
function renderEvLog(){
  var c=$('ev-c'),filtered=S.evFilter==='all'?S.events:S.events.filter(function(e){return e.type===S.evFilter});
  if(filtered.length===0){c.innerHTML='<div style="padding:20px;text-align:center;color:var(--fg-3);font-size:11px">'+(S.evFilter==='all'?'等待事件…':'无 '+S.evFilter+' 事件')+'</div>';return}
  var show=filtered.slice(-100),h='';
  show.forEach(function(e){
    var t=new Date(e.ts).toLocaleTimeString(),d=typeof e.data==='string'?e.data:JSON.stringify(e.data);
    var cl=EV_SHORT[e.type]||e.type.substring(0,5);
    h+='<div class="ev-item"><span class="ev-tm">'+t+'</span><span class="ev-ty '+e.type+'">'+cl+'</span><span class="ev-da">'+esc(d.substring(0,90))+'</span></div>'
  });
  c.innerHTML=h;c.scrollTop=c.scrollHeight
}

/* ═══════════════════════════════════════════
   PLUGIN PANEL
   ═══════════════════════════════════════════ */
async function buildPlugins(){
  var c=$('plugs-c');c.innerHTML='<div class="plug-loading">⟳ 加载中…</div>';
  try{
    var r=await fetch('/api/plugins'),d=await r.json(),
        pl=(d.plugins||[]).filter(function(p){return p.enabled});
    c.innerHTML='';
    if(pl.length===0){var e=div('plug-empty');e.textContent='没有已启用的插件';c.appendChild(e)}
    else{pl.forEach(function(p){renderPluginCard(c,p)})}
    var bar=div('plug-actions');bar.style.cssText='padding:8px;border-top:1px solid var(--bd)';
    bar.innerHTML='<button class="dbg-btn-full" onclick="rescanPlugins()" style="margin:0">🔄 重新扫描并挂载全部</button>';
    c.appendChild(bar)
  }catch(e){c.innerHTML='<div class="plug-empty">插件 API 错误</div>'}
}
function renderPluginCard(container,plugin){
  var card=div('plug-card');
  var icon=plugin.icon||'🧩',allTools=plugin.tools||[],active=allTools.filter(function(t){return!t.masked}).length,masked=allTools.length-active;
  var th='';
  allTools.forEach(function(t){
    var m=t.masked===true,s=m?' style="opacity:0.4;text-decoration:line-through"':'';
    th+='<span class="plug-tag host"'+s+'>'+(t.icon?t.icon+' ':'')+esc(t.display_name||t.name)+(t.version?' '+t.version:'')+(m?' <button class="unmount-btn" style="display:inline;color:var(--accent4);font-size:9px" onclick="unmaskTool(\''+t.name+'\')" title="恢复">↺</button>':' <button class="unmount-btn" style="display:inline;font-size:9px" onclick="maskTool(\''+t.name+'\')" title="屏蔽">✕</button>')+'</span>'
  });
  card.innerHTML='<div class="plug-card-header"><span class="plug-icon">'+icon+'</span><span class="plug-name">'+esc(plugin.name)+'</span><span class="plug-version">v'+esc(plugin.version)+'</span><span style="font-size:10px;color:var(--fg-1);margin-left:auto"><span style="color:var(--accent4)">'+active+'</span>'+(masked>0?' | <span style="color:var(--fg-2)">'+masked+' 已屏蔽</span>':'')+'</span></div><div class="plug-desc">'+esc(plugin.description||'')+'</div><div class="plug-meta"><span>🧰 '+allTools.length+' 个工具</span><span>👤 '+esc(plugin.author)+'</span><span>📁 '+esc(plugin.source)+'</span></div>'+(th?'<div class="plug-tools">'+th+'</div>':'<div class="plug-desc" style="font-size:10px;color:var(--fg-2)">无工具</div>')+'<div class="plug-actions"><button class="plug-btn" onclick="reprobePlugin(\''+esc(plugin.id)+'\')">🔄 重新探测</button></div>';
  container.appendChild(card)
}
async function reprobePlugin(id){try{toast('正在重新探测…','info');var r=await fetch('/api/plugins/'+encodeURIComponent(id)+'/reprobe',{method:'POST'}),d=await r.json();if(d.success){toast('已挂载 '+d.tool_count+' 个工具','success');buildPlugins();buildTools()}else{toast('失败: '+(d.message||''),'error')}}catch(e){toast('错误: '+e.message,'error')}}
async function maskTool(n){try{var r=await fetch('/api/plugins/com.claudez.plugins.host-tools/tools/'+encodeURIComponent(n)+'/mask',{method:'POST'}),d=await r.json();if(d.success){toast('已屏蔽: '+n,'success');buildPlugins();buildTools()}else{toast('失败: '+(d.message||''),'error')}}catch(e){toast('错误: '+e.message,'error')}}
async function unmaskTool(n){try{var r=await fetch('/api/plugins/com.claudez.plugins.host-tools/tools/'+encodeURIComponent(n)+'/unmask',{method:'POST'}),d=await r.json();if(d.success){toast('已恢复: '+n,'success');buildPlugins();buildTools()}else{toast('失败: '+(d.message||''),'error')}}catch(e){toast('错误: '+e.message,'error')}}
async function rescanPlugins(){try{toast('正在重新扫描…','info');var r=await fetch('/api/plugins/discover',{method:'POST'}),d=await r.json();toast('已挂载 '+d.tool_count+' 个工具','success');buildPlugins();buildTools()}catch(e){toast('错误: '+e.message,'error')}}

/* ═══════════════════════════════════════════
   TOOLS PANEL
   ═══════════════════════════════════════════ */
var TCATS={file:{n:'file',c:'#60a5fa'},command:{n:'cmd',c:'#34d399'},shell:{n:'cmd',c:'#34d399'},network:{n:'net',c:'#fb923c'},web:{n:'net',c:'#fb923c'},system:{n:'sys',c:'#f472b6'},artifact:{n:'art',c:'#38bdf8'},subagent:{n:'agent',c:'#c084fc'},workflow:{n:'flow',c:'#34d399'},webhook:{n:'hook',c:'#fbbf24'},package:{n:'pkg',c:'#34d399'},compiler:{n:'comp',c:'#f472b6'},vcs:{n:'vcs',c:'#60a5fa'},container:{n:'ctr',c:'#c084fc'},utility:{n:'util',c:'#8aa0d0'},build:{n:'build',c:'#fb923c'}};
var _builtinI={read:'R',write:'W',edit:'E',glob:'G',grep:'G',bash:'$',web:'W',web_search:'S',process:'P',monitor:'M',subagent:'A',artifact:'B',workflow:'F',webhook:'H'};
var _builtinNames=['read','write','edit','glob','grep','bash','web','web_search','process','monitor','artifact','subagent','workflow','webhook'];
var _builtinCat={read:'file',write:'file',edit:'file',glob:'file',grep:'file',bash:'shell',web:'web',web_search:'web',process:'system',monitor:'system',artifact:'artifact',subagent:'subagent',workflow:'workflow',webhook:'webhook'};
window._toolStats={};window._hostIcons={};
async function buildTools(){
  var c=$('tools-c');c.innerHTML='<div style="padding:20px;text-align:center;color:var(--fg-3);font-size:11px">⟳ 加载中…</div>';
  try{
    var r=await fetch('/api/plugins'),d=await r.json();
    if(!d||!d.tools){renderBuiltin(c);return}
    var all=d.tools||[],grouped={},seen={};
    _builtinNames.forEach(function(n){var cat=_builtinCat[n]||'utility';if(!grouped[cat])grouped[cat]=[];grouped[cat].push({name:n,display_name:n,version:'',category:cat,icon:_builtinI[n]||'?',source:'builtin'});seen[n]=true;window._toolStats[n]=window._toolStats[n]||0});
    all.forEach(function(t){var n=t.name;window._hostIcons[n]=t.icon||'?';if(seen[n])return;seen[n]=true;var cat=t.category||'utility';if(!grouped[cat])grouped[cat]=[];grouped[cat].push({name:n,display_name:t.display_name||n,version:t.version||'',category:cat,icon:t.icon||'?',source:'host',masked:t.masked===true});window._toolStats[n]=0});
    c.innerHTML='';
    var order=['file','shell','command','network','web','system','package','compiler','vcs','container','build','artifact','subagent','workflow','webhook','utility'];
    order.forEach(function(ck){
      var tools=grouped[ck];if(!tools||tools.length===0)return;
      var m=TCATS[ck];if(!m)return;
      var $c=c.appendChild(div('tool-cat'));$c.style.color=m.c;$c.textContent=m.n+' ('+tools.length+')';
      var g=div('tool-grd');
      tools.forEach(function(t){
        var el=div('tool-item'),masked=t.masked===true;
        if(t.source==='host')el.classList.add('host-tool');
        if(masked)el.style.opacity='.45';
        var v=t.version?'<span class="tv">'+esc(t.version)+'</span>':'';
        el.innerHTML='<span class="td idle" id="td-'+t.name+'"></span><span class="ti">'+t.icon+'</span><span class="tn">'+esc(t.display_name)+(masked?' (已屏蔽)':'')+'</span>'+v+'<span class="tc" id="tcnt-'+t.name+'">0</span>';
        if(t.source==='host'){
          var ub=document.createElement('button');ub.className='unmount-btn';
          if(masked){ub.textContent='↺';ub.style.color='var(--accent4)';ub.title='恢复';ub.onclick=function(e){e.stopPropagation();unmaskTool(t.name)}}
          else{ub.textContent='✕';ub.title='屏蔽';ub.onclick=function(e){e.stopPropagation();maskTool(t.name)}}
          el.appendChild(ub)
        }
        g.appendChild(el)
      });
      c.appendChild(g)
    });
    $('st-c').textContent=Object.keys(seen).length
  }catch(e){c.innerHTML='';renderBuiltin(c)}
}
function renderBuiltin(c){
  c.innerHTML='';var order=['file','shell','web','system','artifact','subagent','workflow','webhook'];
  order.forEach(function(ck){
    var m=TCATS[ck];if(!m)return;
    var tools={file:['read','write','edit','glob','grep'],shell:['bash'],web:['web','web_search'],system:['process','monitor'],artifact:['artifact'],subagent:['subagent'],workflow:['workflow'],webhook:['webhook']}[ck]||[];
    if(tools.length===0)return;
    var hdr=div('tool-cat');hdr.style.color=m.c;hdr.textContent=m.n+' ('+tools.length+')';c.appendChild(hdr);
    var g=div('tool-grd');
    tools.forEach(function(n){window._toolStats[n]=window._toolStats[n]||0;var el=div('tool-item');el.innerHTML='<span class="td idle" id="td-'+n+'"></span><span class="ti">'+(_builtinI[n]||'?')+'</span><span class="tn">'+n+'</span><span class="tc" id="tcnt-'+n+'">0</span>';g.appendChild(el)});
    c.appendChild(g)
  })
}
function updateTD(n,s){
  var d=$('td-'+n);if(d)d.className='td '+s;
  if(s==='done'||s==='error'){window._toolStats[n]=(window._toolStats[n]||0)+1;var c=$('tcnt-'+n);if(c)c.textContent=window._toolStats[n]}
}
// Hook into tool display
var _o1=addToolResult;addToolResult=function(n,e,d,r,p){_o1(n,e,d,r,p);updateTD(n,e?'error':'done')};
var _o2=addToolCall;addToolCall=function(n,p,e){updateTD(n,'running');_o2(n,p,e)};

/* ═══════════════════════════════════════════
   CONFIG PANEL (GLASSMORPHISM)
   ═══════════════════════════════════════════ */
function buildConfig(){
  var c=$('cfg-c');
  c.innerHTML=
    '<div class="cfg-section">'+
      '<div class="cfg-section-title">🤖 LLM 提供商</div>'+
      '<div class="cfg-row"><label class="cfg-label">提供商</label>'+
        '<select class="cfg-select" id="cfg-provider"><option value="deepseek">DeepSeek</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic (Claude)</option></select></div>'+
      '<div class="cfg-row"><label class="cfg-label">模型</label>'+
        '<input class="cfg-input" id="cfg-model" placeholder="例如 deepseek-chat" spellcheck="false"></div>'+
      '<div class="cfg-row"><label class="cfg-label">API 密钥 <span style="color:var(--fg-3);font-weight:400">(设置后不再返回)</span></label>'+
        '<input class="cfg-input cfg-input-pw" id="cfg-apikey" type="password" placeholder="sk-… (仅内存存储)" autocomplete="off"></div>'+
    '</div>'+
    '<div class="cfg-section">'+
      '<div class="cfg-section-title">🎯 生成参数</div>'+
      '<div class="cfg-row"><label class="cfg-label">温度 <span class="cfg-unit" id="cfg-temp-val">0.0</span></label>'+
        '<div class="cfg-slider"><input type="range" id="cfg-temp" min="0" max="2" step="0.05" value="0"><span class="cfg-slider-val" id="cfg-temp-display">0.0</span></div></div>'+
      '<div class="cfg-row"><label class="cfg-label">最大输出 Token <span class="cfg-unit" id="cfg-tk-val">8192</span></label>'+
        '<div class="cfg-slider"><input type="range" id="cfg-tokens" min="256" max="32768" step="128" value="8192"><span class="cfg-slider-val" id="cfg-tk-display">8,192</span></div></div>'+
      '<div class="cfg-row"><label class="cfg-label">超时时间 (秒) <span class="cfg-unit" id="cfg-to-val">3600</span></label>'+
        '<div class="cfg-slider"><input type="range" id="cfg-timeout" min="30" max="14400" step="30" value="3600"><span class="cfg-slider-val" id="cfg-to-display">3,600</span></div></div>'+
    '</div>'+
    '<div class="cfg-section">'+
      '<div class="cfg-section-title">⚙️ 模式</div>'+
      '<div class="cfg-row"><label class="cfg-label">工作流</label>'+
        '<select class="cfg-select" id="cfg-workflow"><option value="agent">Agent (全功能)</option><option value="chat">对话</option><option value="research">研究</option><option value="coding">编程</option><option value="debug">调试</option></select></div>'+
      '<div class="cfg-row"><label class="cfg-label">权限模式</label>'+
        '<select class="cfg-select" id="cfg-perm"><option value="auto">自动 (推荐)</option><option value="ask">询问</option><option value="deny">全部拒绝</option><option value="readonly">只读</option></select></div>'+
    '</div>'+
    '<div class="cfg-section">'+
      '<div class="cfg-section-title">🔘 开关</div>'+
      '<div class="cfg-toggle" id="cfg-thinking-row">'+
        '<div class="cfg-toggle-track" id="cfg-thinking-track"><div class="cfg-toggle-knob"></div></div>'+
        '<span class="cfg-toggle-label">禁用思考模式 <span style="color:var(--fg-3)">(节省 Token)</span></span></div>'+
      '<div class="cfg-toggle" id="cfg-memory-row">'+
        '<div class="cfg-toggle-track" id="cfg-memory-track"><div class="cfg-toggle-knob"></div></div>'+
        '<span class="cfg-toggle-label">启用语义记忆 <span style="color:var(--fg-3)">(ChromaDB)</span></span></div>'+
    '</div>'+
    '<div class="cfg-actions">'+
      '<button class="cfg-btn" id="cfg-save-btn">💾 保存配置</button>'+
      '<button class="cfg-btn-sec" onclick="loadConfig()">⟳ 从服务器重新加载</button>'+
      '<div class="cfg-status" id="cfg-status"></div>'+
    '</div>';

  // Toggle click handlers
  $('cfg-thinking-track').onclick=function(){this.classList.toggle('on')};
  $('cfg-memory-track').onclick=function(){this.classList.toggle('on')};

  // Slider live updates
  var tempSl=$('cfg-temp'),tempD=$('cfg-temp-display'),tempV=$('cfg-temp-val');
  tempSl.addEventListener('input',function(){var v=parseFloat(this.value).toFixed(2);tempD.textContent=v;tempV.textContent=v});

  var tkSl=$('cfg-tokens'),tkD=$('cfg-tk-display'),tkV=$('cfg-tk-val');
  tkSl.addEventListener('input',function(){var v=parseInt(this.value);tkD.textContent=v.toLocaleString();tkV.textContent=v.toLocaleString()});

  var toSl=$('cfg-timeout'),toD=$('cfg-to-display'),toV=$('cfg-to-val');
  toSl.addEventListener('input',function(){var v=parseInt(this.value);toD.textContent=v.toLocaleString();toV.textContent=v.toLocaleString()});

  // Save button
  $('cfg-save-btn').onclick=C.saveConfig;

  // Load existing config
  loadConfig()
}

async function loadConfig(){
  var btn=$('cfg-save-btn');if(btn)btn.disabled=true;
  try{
    var r=await fetch('/api/config'),d=await r.json();
    if(d.status==='error'){showCfgStatus('加载配置失败','err');return}
    S.config=d;

    // Provider
    var el=$('cfg-provider');if(el){var idx=['deepseek','openai','anthropic'].indexOf(d.provider||'');if(idx>=0)el.selectedIndex=idx}

    // Model
    el=$('cfg-model');if(el)el.value=d.model||'';
    el=$('cfg-apikey');if(el)el.value=d.has_api_key?'············':'';

    // Sliders
    el=$('cfg-temp');if(el){el.value=d.temperature||0;$('cfg-temp-display').textContent=(d.temperature||0).toFixed(2);$('cfg-temp-val').textContent=(d.temperature||0).toFixed(2)}
    el=$('cfg-tokens');if(el){var tk=d.max_tokens||8192;el.value=tk;$('cfg-tk-display').textContent=tk.toLocaleString();$('cfg-tk-val').textContent=tk.toLocaleString()}
    el=$('cfg-timeout');if(el){var to=d.timeout||3600;el.value=to;$('cfg-to-display').textContent=to.toLocaleString();$('cfg-to-val').textContent=to.toLocaleString()}

    // Workflow
    el=$('cfg-workflow');if(el){var wf=['agent','chat','research','coding','debug'].indexOf(d.workflow_mode||'agent');if(wf>=0)el.selectedIndex=wf}

    // Permission
    el=$('cfg-perm');if(el){var pm=['auto','ask','deny','readonly'].indexOf(d.permission_mode||'auto');if(pm>=0)el.selectedIndex=pm}

    // Toggles
    var th=$('cfg-thinking-track');if(th){if(d.disable_thinking!==false)th.classList.add('on')}
    var mem=$('cfg-memory-track');if(mem){if(d.enable_memory!==false)mem.classList.add('on')}

    // Update header
    $('st-m').textContent=d.model||'—'

  }catch(e){showCfgStatus('加载错误: '+e.message,'err')}
  if(btn)btn.disabled=false;
}

function showCfgStatus(msg,type){
  var el=$('cfg-status');
  if(!el)return;
  el.textContent=msg;
  el.className='cfg-status show '+(type||'ok');
  if(type!=='err')setTimeout(function(){el.classList.remove('show')},5000);
}

function saveConfig(){
  var btn=$('cfg-save-btn');if(!btn||btn.disabled)return;
  btn.disabled=true;btn.textContent='⟳ 保存中…';
  showCfgStatus('正在保存…','');

  var body={};
  var pv=$('cfg-provider');if(pv)body.provider=pv.value;
  var mdl=$('cfg-model');if(mdl&&mdl.value.trim())body.model=mdl.value.trim();
  var ak=$('cfg-apikey');if(ak&&ak.value.trim()&&ak.value!=='············')body.api_key=ak.value.trim();
  body.temperature=parseFloat($('cfg-temp').value);
  body.max_tokens=parseInt($('cfg-tokens').value);
  body.timeout=parseInt($('cfg-timeout').value);
  if($('cfg-workflow'))body.workflow_mode=$('cfg-workflow').value;
  if($('cfg-perm'))body.permission_mode=$('cfg-perm').value;
  var th=$('cfg-thinking-track');if(th)body.disable_thinking=th.classList.contains('on');
  var mem=$('cfg-memory-track');if(mem)body.enable_memory=mem.classList.contains('on');

  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  .then(function(r){return r.json()})
  .then(function(d){
    btn.disabled=false;btn.textContent='💾 保存配置';
    if(d.status==='ok'){
      showCfgStatus('✓ 已保存: '+((d.changes||[]).join(', ')||'所有设置'),'ok');
      loadConfig();
      toast('配置已保存','success')
    }else if(d.status==='partial'){
      var msg='✓ '+(d.changes||[]).join(', ')+' | ⚠ '+(d.errors||[]).join('; ');
      showCfgStatus(msg,'partial');
      loadConfig();
      toast('部分保存成功 — 请检查错误','info')
    }else{
      showCfgStatus('✗ '+(d.message||'保存失败'),'err');
      toast('保存失败','error')
    }
  })
  .catch(function(e){
    btn.disabled=false;btn.textContent='💾 保存配置';
    showCfgStatus('✗ 网络错误: '+e.message,'err');
    toast('网络错误','error')
  })
}

/* ═══════════════════════════════════════════
   DEBUG PANEL
   ═══════════════════════════════════════════ */
function updateDebugSummary(){
  fetch('/api/debug/summary').then(function(r){return r.json()}).then(function(d){
    var el=$('dbg-summary');if(!el)return;
    var s=d.summary||d||{};
    el.textContent='工具调用: '+(s.total_tool_calls||0)+' | API: '+(s.total_api_calls||0)+' | 成功: '+(s.successful_tools||0)+' | 失败: '+(s.failed_tools||0)+' | 工具耗时: '+(s.total_tool_duration_ms/1000).toFixed(1)+'s | API耗时: '+(s.total_api_duration_ms/1000).toFixed(1)+'s';
    var sg=$('dbg-stats');
    if(sg){
      sg.innerHTML=
        '<div class="dbg-stat-item"><div class="dbg-stat-val">'+(s.total_tool_calls||0)+'</div><div class="dbg-stat-l">工具调用</div></div>'+
        '<div class="dbg-stat-item"><div class="dbg-stat-val">'+(s.total_api_calls||0)+'</div><div class="dbg-stat-l">API 调用</div></div>'+
        '<div class="dbg-stat-item"><div class="dbg-stat-val" style="color:'+(s.failed_tools>0?'var(--accent6)':'var(--accent4)')+'">'+(s.successful_tools||0)+'</div><div class="dbg-stat-l">成功</div></div>'+
        '<div class="dbg-stat-item"><div class="dbg-stat-val" style="color:'+(s.failed_tools>0?'var(--accent6)':'var(--fg-1)')+'">'+(s.failed_tools||0)+'</div><div class="dbg-stat-l">失败</div></div>'
    }
  }).catch(function(){})
}

function updatePluginDebug(){
  fetch('/api/debug/plugins').then(function(r){return r.json()}).then(function(d){
    var el=$('dbg-plugins');if(!el)return;
    var logs=d.logs||[],h='<div style="margin-bottom:4px;font-size:9px;color:var(--fg-3)">'+logs.length+' 个事件</div>';
    logs.slice(-80).reverse().forEach(function(l){
      var c=l.event==='ERR'?'var(--accent6)':l.event==='WARN'?'var(--accent5)':'var(--fg-1)';
      h+='<div style="border-bottom:1px solid rgba(255,255,255,0.02);padding:1px 0"><span style="color:var(--fg-3);width:46px;display:inline-block">'+(l.ts?esc(l.ts):'')+'</span><span style="color:'+c+';font-weight:600;width:44px;display:inline-block">'+esc(l.event||'')+'</span><span>'+esc(l.msg||'')+'</span></div>'
    });
    el.innerHTML=h;
    if(!logs.length)el.innerHTML='<div style="color:var(--fg-2);font-size:10px">没有插件调试事件</div>'
  }).catch(function(){})
}

/* ═══════════════════════════════════════════
   TOAST
   ═══════════════════════════════════════════ */
var TOAST_ICONS={info:'💡',success:'✓',error:'✗'};
function toast(msg,t){
  t=t||'info';
  var el=div('toast '+(t==='success'?' s':t==='error'?' e':' i'));
  el.innerHTML='<span class="toast-icon">'+(TOAST_ICONS[t]||'i')+'</span><span>'+msg+'</span>';
  toasts.appendChild(el);
  setTimeout(function(){el.classList.add('out');setTimeout(function(){el.remove()},250)},2800)
}

/* ═══════════════════════════════════════════
   SCROLL
   ═══════════════════════════════════════════ */
msgs.addEventListener('scroll',function(){
  var th=60;
  S.ab=(msgs.scrollHeight-msgs.scrollTop-msgs.clientHeight)<th;
  scrollH.classList.toggle('show',!S.ab)
});
scrollH.onclick=function(){S.ab=1;scrollB();this.classList.remove('show')};

/* ═══════════════════════════════════════════
   EXPORTS
   ═══════════════════════════════════════════ */
window.C={
  send:send,stop:stop,clear:clear,
  exportDebug:function(){fetch('/api/debug').then(function(r){return r.text()}).then(function(t){if(navigator.clipboard)navigator.clipboard.writeText(t).then(function(){toast('调试日志已复制 (JSON)','success')})}).catch(function(){toast('复制失败','error')})},
  exportDebugMD:function(){fetch('/api/debug/markdown').then(function(r){return r.text()}).then(function(t){if(navigator.clipboard)navigator.clipboard.writeText(t).then(function(){toast('调试报告已复制 (Markdown)','success')})}).catch(function(){toast('复制失败','error')})},
  updateDebugSummary:updateDebugSummary,
  updatePluginDebug:updatePluginDebug,
  saveConfig:saveConfig,
  loadConfig:loadConfig,
  reprobePlugin:reprobePlugin,maskTool:maskTool,unmaskTool:unmaskTool,rescanPlugins:rescanPlugins
};
window.maskTool=maskTool;window.unmaskTool=unmaskTool;window.reprobePlugin=reprobePlugin;window.rescanPlugins=rescanPlugins;

/* ═══════════════════════════════════════════
   INIT
   ═══════════════════════════════════════════ */
function init(){
  // Input auto-resize
  ib.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,100)+'px'});
  ib.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});

  // Tab switching with animation
  document.querySelectorAll('.p-tab').forEach(function(t){
    t.addEventListener('click',function(){
      document.querySelectorAll('.p-tab,.p-content').forEach(function(x){x.classList.remove('active')});
      t.classList.add('active');
      var p=$('pn-'+t.dataset.t);
      if(p){p.classList.add('active')}
    })
  });

  // Build all panels
  buildTools();
  renderEvBar();
  buildConfig();
  buildPlugins();
  connectSSE();

  // Loading screen
  setTimeout(function(){$('loading').classList.add('hidden')},500);
  setTimeout(function(){addSys('ClaudeZ v2.1 — AI 智能体');toast('欢迎使用','success')},700)
}

if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init()
})();
